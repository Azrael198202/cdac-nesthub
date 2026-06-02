from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def plan(payload: dict[str, Any]) -> dict[str, Any]:
    """Runtime-asset default planner for missing-template acquisition.

    Boundary:
    - This file is a packaged runtime asset, not ai_core logic.
    - It contains only a generic planning contract and local-model invocation.
    - It must not embed concrete capability implementations or domain examples.
    - If the local model is unavailable, it fails explicitly so the acquisition
      pipeline can use evidence/self-repair rather than silently generating an
      unsupported artifact.
    """
    request_text = str(payload.get("user_input") or "")
    identity = payload.get("identity_contract") if isinstance(payload.get("identity_contract"), dict) else {}
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
    contract = payload.get("required_blueprint_contract") or payload.get("required_template_contract")

    model_payload = _try_model_planner(
        request_text=request_text,
        identity=identity,
        evidence=evidence,
        contract=contract,
    )
    if isinstance(model_payload, dict) and isinstance(model_payload.get("blueprint"), dict):
        model_payload.setdefault("status", "planned")
        model_payload.setdefault("confidence_score", 0.76)
        model_payload.setdefault("needs_external_evidence", False)
        model_payload.setdefault("planner_engine", "local_model")
        return model_payload

    fallback = _deterministic_blueprint_fallback(
        request_text=request_text,
        identity=identity,
        evidence=evidence,
        model_attempt=model_payload if isinstance(model_payload, dict) else {"status": "skipped"},
    )
    if os.environ.get("AI_CORE_DISABLE_CAPABILITY_BLUEPRINT_FALLBACK", "").lower() in {"1", "true", "yes"}:
        return {
            "status": "planner_failed",
            "reason": "local_model_blueprint_unavailable_or_invalid",
            "confidence_score": 0,
            "needs_external_evidence": True,
            "model_planner_attempt": model_payload if isinstance(model_payload, dict) else {"status": "skipped"},
            "fallback_available": fallback,
        }
    return fallback


def _try_model_planner(*, request_text: str, identity: dict[str, Any], evidence: dict[str, Any], contract: Any) -> dict[str, Any]:
    if os.environ.get("AI_CORE_DISABLE_LOCAL_CAPABILITY_MODEL", "").lower() in {"1", "true", "yes"}:
        return {"status": "skipped", "reason": "local_capability_model_disabled"}
    host = os.environ.get("OLLAMA_HOST") or os.environ.get("AI_CORE_OLLAMA_HOST") or "http://127.0.0.1:11434"
    model, model_source = _resolve_planner_model()
    attempts = []
    first_prompt = _model_prompt(request_text=request_text, identity=identity, evidence=evidence, contract=contract)
    first = _call_ollama_json_planner(
        host=host,
        model=model,
        model_source=model_source,
        prompt=first_prompt,
        force_json=True,
        timeout=float(os.environ.get("AI_CORE_CAPABILITY_PLANNER_TIMEOUT", "15")),
        prompt_stage="capability_blueprint_planning",
    )
    attempts.append(first)
    if isinstance(first.get("blueprint"), dict):
        return first

    # Small local models sometimes return an empty response when Ollama JSON mode
    # is combined with a long schema prompt. Retry once with a smaller prompt and
    # without provider-side JSON forcing; the parser still accepts only JSON.
    retry_prompt = _compact_model_prompt(request_text=request_text, identity=identity, evidence=evidence, contract=contract)
    retry = _call_ollama_json_planner(
        host=host,
        model=model,
        model_source=model_source,
        prompt=retry_prompt,
        force_json=False,
        timeout=float(os.environ.get("AI_CORE_CAPABILITY_PLANNER_COMPACT_TIMEOUT", os.environ.get("AI_CORE_CAPABILITY_PLANNER_TIMEOUT", "15"))),
        prompt_stage="capability_blueprint_planning_compact",
    )
    attempts.append(retry)
    if isinstance(retry.get("blueprint"), dict):
        retry["attempts"] = attempts
        retry["compact_retry_used"] = True
        retry["model_source"] = model_source
        return retry
    return {"status": "planner_failed", "reason": str(retry.get("reason") or first.get("reason") or "model_returned_no_valid_blueprint"), "model": model, "model_source": model_source, "attempts": attempts}


def _resolve_planner_model() -> tuple[str, str]:
    """Resolve the local planner model and make the selected engine auditable.

    Priority:
    1. explicit planner/model environment variables for server deployments;
    2. runtime UI selection in configs/model_selection.json;
    3. neutral default only when no runtime selection exists.
    """
    env_model = (
        os.environ.get("AI_CORE_CAPABILITY_PLANNER_MODEL")
        or os.environ.get("AI_CORE_SELECTED_LOCAL_MODEL")
        or os.environ.get("OLLAMA_MODEL")
        or ""
    ).strip()
    if env_model:
        return env_model, "environment"
    for root in _candidate_project_roots():
        path = root / "configs" / "model_selection.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        selected = str(data.get("selected_local_model_id") or data.get("initial_model_id") or data.get("model") or "").strip()
        mode = str(data.get("mode") or "").strip().casefold()
        if selected and mode in {"", "local_only", "hybrid", "local_first"}:
            return selected, str(path)
    return "qwen3.5:4b-q4_k_m", "default_no_runtime_selection"


def _candidate_project_roots() -> list[Path]:
    roots: list[Path] = []
    for key in ("AI_CORE_PROJECT_ROOT", "PROJECT_ROOT", "CDAC_NESTHUB_ROOT"):
        value = os.environ.get(key, "").strip()
        if value:
            roots.append(Path(value).expanduser())
    try:
        roots.append(Path.cwd().resolve())
    except Exception:
        pass
    try:
        current = Path(__file__).resolve()
        roots.extend([current.parent, *current.parents])
    except Exception:
        pass

    discovered: list[Path] = []
    for root in roots:
        try:
            resolved = root.resolve()
        except Exception:
            resolved = root
        candidates = [resolved]
        try:
            candidates.extend(list(resolved.parents))
        except Exception:
            pass
        for candidate in candidates:
            if (candidate / "configs" / "model_selection.json").exists():
                discovered.append(candidate)
            if (candidate / "ai_core").exists() and (candidate / "runtime_assets").exists():
                discovered.append(candidate)
    unique: list[Path] = []
    for root in [*discovered, *roots]:
        try:
            root = root.resolve()
        except Exception:
            pass
        if root not in unique:
            unique.append(root)
    return unique


def _call_ollama_json_planner(*, host: str, model: str, model_source: str, prompt: str, force_json: bool, timeout: float, prompt_stage: str) -> dict[str, Any]:
    attempt_started = time.monotonic()
    attempt_id = hashlib.sha256((str(model) + str(prompt_stage) + str(len(prompt))).encode("utf-8", errors="ignore")).hexdigest()[:12]
    _emit_planner_event(
        event="PlannerModelAttempt",
        status="running",
        message="Planner model attempt started",
        data={
            "stage_label": "BlueprintPlanner",
            "action": f"Calling planner model {model}",
            "console_message": f"Planner model attempt started: {model}",
            "model": model,
            "model_source": model_source,
            "force_json": force_json,
            "prompt_stage": prompt_stage,
            "attempt_id": attempt_id,
            "timeout_seconds": timeout,
            "prompt_chars": len(str(prompt or "")),
        },
    )
    body_payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0, "num_ctx": int(os.environ.get("AI_CORE_CAPABILITY_PLANNER_NUM_CTX", "3072")), "num_predict": int(os.environ.get("AI_CORE_CAPABILITY_PLANNER_NUM_PREDICT", "512")), "think": False},
    }
    if force_json:
        body_payload["format"] = "json"
    body = json.dumps(body_payload).encode("utf-8")
    try:
        req = urllib.request.Request(host.rstrip("/") + "/api/generate", data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        outer = json.loads(raw or "{}")
        text = str(outer.get("response") or "").strip()
        parsed = _parse_json_object(text)
        if not isinstance(parsed, dict):
            _audit_model_prompt(stage=prompt_stage, model=model, model_source=model_source, prompt=prompt, status="model_returned_non_json", route="local_model")
            _emit_planner_event(
                event="PlannerModelAttempt",
                status="failed",
                message="Planner model did not return valid JSON",
                data={
                    "stage_label": "BlueprintPlanner",
                    "action": "Planner model returned non-JSON; retry or fallback will be used",
                    "console_message": "Planner model returned non-JSON",
                    "model": model,
                    "model_source": model_source,
                    "force_json": force_json,
                    "raw_empty": not bool(text),
                    "attempt_id": attempt_id,
                    "duration_ms": int((time.monotonic() - attempt_started) * 1000),
                    "timeout_seconds": timeout,
                    "diagnosis": "Provider returned empty or non-JSON text; strict parser rejected the planner response.",
                },
            )
            return {"status": "planner_failed", "reason": "model_returned_non_json", "raw_excerpt": text[:500], "model": model, "model_source": model_source, "force_json": force_json, "raw_empty": not bool(text), "attempt_id": attempt_id, "duration_ms": int((time.monotonic() - attempt_started) * 1000), "timeout_seconds": timeout}
        blueprint = parsed.get("blueprint") if isinstance(parsed.get("blueprint"), dict) else parsed
        if not isinstance(blueprint, dict):
            _audit_model_prompt(stage=prompt_stage, model=model, model_source=model_source, prompt=prompt, status="model_returned_no_blueprint", route="local_model")
            return {"status": "planner_failed", "reason": "model_returned_no_blueprint", "raw_excerpt": text[:500], "model": model, "model_source": model_source, "force_json": force_json}
        _audit_model_prompt(stage=prompt_stage, model=model, model_source=model_source, prompt=prompt, status="planned", route="local_model")
        _emit_planner_event(
            event="PlannerModelAttempt",
            status="completed",
            message="Planner model returned a valid blueprint",
            data={
                "stage_label": "BlueprintPlanner",
                "action": "Planner model produced valid blueprint JSON",
                "console_message": "Planner model returned a valid blueprint",
                "model": model,
                "model_source": model_source,
                "force_json": force_json,
                "attempt_id": attempt_id,
                "duration_ms": int((time.monotonic() - attempt_started) * 1000),
                "timeout_seconds": timeout,
            },
        )
        return {
            "status": "planned",
            "confidence_score": float(parsed.get("confidence_score") or parsed.get("confidence") or 0.76),
            "needs_external_evidence": _to_bool(parsed.get("needs_external_evidence", False), default=False),
            "blueprint": blueprint,
            "model": model,
            "model_source": model_source,
            "force_json": force_json,
            "attempt_id": attempt_id,
            "duration_ms": int((time.monotonic() - attempt_started) * 1000),
            "timeout_seconds": timeout,
        }
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
        _audit_model_prompt(stage=prompt_stage, model=model, model_source=model_source, prompt=prompt, status=f"{exc.__class__.__name__}", route="local_model")
        _emit_planner_event(
            event="PlannerModelAttempt",
            status="failed",
            message=f"Planner model attempt failed: {exc.__class__.__name__}",
            data={
                "stage_label": "BlueprintPlanner",
                "action": f"Planner model attempt failed: {exc.__class__.__name__}",
                "console_message": f"Planner model attempt failed: {exc.__class__.__name__}",
                "model": model,
                "model_source": model_source,
                "force_json": force_json,
                "attempt_id": attempt_id,
                "duration_ms": int((time.monotonic() - attempt_started) * 1000),
                "timeout_seconds": timeout,
                "diagnosis": "Local planner call failed before a valid JSON object was accepted.",
            },
        )
        return {"status": "planner_failed", "reason": f"local_model_unavailable_or_invalid: {exc.__class__.__name__}", "model": model, "model_source": model_source, "force_json": force_json, "attempt_id": attempt_id, "duration_ms": int((time.monotonic() - attempt_started) * 1000), "timeout_seconds": timeout}
    except Exception as exc:
        _audit_model_prompt(stage=prompt_stage, model=model, model_source=model_source, prompt=prompt, status=f"{exc.__class__.__name__}", route="local_model")
        _emit_planner_event(
            event="PlannerModelAttempt",
            status="failed",
            message=f"Planner model error: {exc.__class__.__name__}",
            data={
                "stage_label": "BlueprintPlanner",
                "action": f"Planner model error: {exc.__class__.__name__}",
                "console_message": f"Planner model error: {exc.__class__.__name__}",
                "model": model,
                "model_source": model_source,
                "force_json": force_json,
                "attempt_id": attempt_id,
                "duration_ms": int((time.monotonic() - attempt_started) * 1000),
                "timeout_seconds": timeout,
                "diagnosis": "Unexpected local planner error; fallback will be used when allowed.",
            },
        )
        return {"status": "planner_failed", "reason": f"local_model_error: {exc.__class__.__name__}: {str(exc)[:300]}", "model": model, "model_source": model_source, "force_json": force_json, "attempt_id": attempt_id, "duration_ms": int((time.monotonic() - attempt_started) * 1000), "timeout_seconds": timeout}


def _emit_planner_event(*, event: str, status: str, message: str, data: dict[str, Any] | None = None) -> None:
    try:
        from ai_core.runtime.observability.runtime_console import emit_console_event
        emit_console_event(area="capability_acquisition", event=event, status=status, message=message, data=data or {})
    except Exception:
        return


def _deterministic_blueprint_fallback(*, request_text: str, identity: dict[str, Any], evidence: dict[str, Any], model_attempt: dict[str, Any]) -> dict[str, Any]:
    """Create a minimal blueprint when the model cannot produce valid JSON.

    This fallback is structural and generic. It does not implement a concrete
    capability and it does not hardcode runtime values. It extracts only fields
    that the user explicitly declared as schema fields; otherwise it creates
    neutral placeholder fields so ArtifactGenerator can produce a dry-run
    candidate for validation.
    """
    text = str(request_text or "")
    lowered = text.casefold()

    connection_fields = _extract_schema_section_fields(text, section_name="connection")
    secret_fields = _extract_schema_section_fields(text, section_name="secret")
    input_fields = _extract_schema_section_fields(text, section_name="input")

    requires_connection = bool(connection_fields) or any(token in lowered for token in ("connection", "endpoint", "host", "port", "url"))
    requires_secret = bool(secret_fields) or any(token in lowered for token in ("secret", "credential", "token", "key", "password", "auth"))

    if not input_fields:
        input_fields = _extract_backticked_fields(text) or ["field_1"]
    if requires_connection and not connection_fields:
        connection_fields = ["connection_value"]
    if requires_secret and not secret_fields:
        secret_fields = ["secret_value"]

    _emit_planner_event(
        event="DeterministicBlueprintFallback",
        status="completed",
        message="Deterministic blueprint fallback generated",
        data={
            "stage_label": "BlueprintPlanner",
            "action": "Model blueprint was unavailable; generated a neutral fallback blueprint",
            "console_message": "Deterministic blueprint fallback generated",
            "fallback_reason": str(model_attempt.get("reason") or model_attempt.get("status") or "model_blueprint_unavailable"),
            "required_inputs_count": len(input_fields),
            "connection_fields_count": len(connection_fields),
            "secret_fields_count": len(secret_fields),
        },
    )
    return {
        "status": "planned",
        "confidence_score": 0.51,
        "needs_external_evidence": False,
        "planner_engine": "deterministic_blueprint_fallback",
        "fallback_used": True,
        "fallback_reason": str(model_attempt.get("reason") or model_attempt.get("status") or "model_blueprint_unavailable"),
        "model_planner_attempt": model_attempt,
        "blueprint": {
            "capability_category": "adapter",
            "requires_connection": bool(requires_connection),
            "requires_secret": bool(requires_secret),
            "required_inputs": input_fields,
            "required_connection_fields": connection_fields,
            "required_secret_fields": secret_fields,
            "approval_mode": "always",
            "execution_mode": "adapter",
            "verification_mode": "dry_run",
        },
    }


def _extract_backticked_fields(text: str) -> list[str]:
    found: list[str] = []
    for raw in re.findall(r"`([^`]{1,64})`", text):
        name = _safe_field_name(raw)
        if name and name not in found:
            found.append(name)
    return found[:12]


def _extract_schema_section_fields(text: str, *, section_name: str) -> list[str]:
    """Extract explicitly declared schema fields from neutral schema sections.

    Accepted patterns are intentionally generic, for example:
    - "Input schema must include:" followed by bullet lines
    - "Connection schema must include only:" followed by bullet lines
    - inline: "input schema: a, b, c"
    Ordinary instruction lines such as "store connection values through UI" are
    ignored so they do not become schema field names.
    """
    section = section_name.casefold()
    found: list[str] = []
    lines = text.splitlines()
    active = False
    for line in lines:
        stripped = line.strip()
        folded = stripped.casefold()
        if re.search(rf"\b{re.escape(section)}\s+schema\b", folded):
            active = True
            after = re.split(r":", stripped, maxsplit=1)
            if len(after) == 2 and after[1].strip():
                for item in re.split(r"[,;]", after[1]):
                    name = _safe_field_name(item)
                    if name and name not in found and name not in _SCHEMA_STOP_WORDS:
                        found.append(name)
            continue
        if active:
            if not stripped:
                continue
            if re.search(r"\b(input|connection|secret|approval|output|verification|runtime)\s+schema\b", folded) and not re.search(rf"\b{re.escape(section)}\s+schema\b", folded):
                break
            bullet = re.match(r"^[*\-•]\s*([A-Za-z_][A-Za-z0-9_]{0,63})\b", stripped)
            if bullet:
                name = _safe_field_name(bullet.group(1))
                if name and name not in found and name not in _SCHEMA_STOP_WORDS:
                    found.append(name)
                continue
            # Stop the section when natural prose resumes.
            if not stripped.startswith(("*", "-", "•")):
                break
    return found[:12]


_SCHEMA_STOP_WORDS = {
    "schema", "include", "includes", "must", "only", "required", "field", "fields",
    "input", "connection", "secret", "approval", "policy", "support", "default",
}


def _safe_field_name(value: Any) -> str:
    name = re.sub(r"[^a-zA-Z0-9_]+", "_", str(value or "").strip()).strip("_").lower()
    if not name:
        return ""
    if name[0].isdigit():
        name = "field_" + name
    return name[:64]

def _model_prompt(*, request_text: str, identity: dict[str, Any], evidence: dict[str, Any], contract: Any) -> str:
    return (
        "Generate ONLY one valid JSON object. No markdown. "
        "The object must contain confidence_score, needs_external_evidence, and blueprint. "
        "blueprint fields: capability_category, requires_connection, requires_secret, required_inputs, "
        "required_connection_fields, required_secret_fields, approval_mode, execution_mode, verification_mode. "
        "Use neutral field names. Do not generate code. Do not generate schemas. Do not hardcode runtime values.\n"
        f"Contract: {json.dumps(_compact_contract(contract), ensure_ascii=False)[:700]}\n"
        f"Identity: {json.dumps(identity, ensure_ascii=False)[:500]}\n"
        f"Request: {str(request_text or '')[:900]}"
    )

def _compact_model_prompt(*, request_text: str, identity: dict[str, Any], evidence: dict[str, Any], contract: Any) -> str:
    return (
        "Return JSON only: {\"confidence_score\":0.0-1.0,\"needs_external_evidence\":false,\"blueprint\":{...}}. "
        "Blueprint only, no code, no implementation template. "
        "Required blueprint keys: capability_category, requires_connection, requires_secret, required_inputs. "
        f"Request: {str(request_text or '')[:600]}"
    )

def _compact_contract(contract: Any) -> Any:
    if not isinstance(contract, dict):
        return contract
    keep = [
        "required_top_level_keys",
        "required_file_contract",
        "required_schema_contract",
        "required_runtime_contract",
        "required_validation_contract",
    ]
    out = {k: contract.get(k) for k in keep if k in contract}
    return out or contract

def _parse_json_object(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:
        return None


def _to_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().casefold()
    if text in {"true", "1", "yes", "y", "on"}:
        return True
    if text in {"false", "0", "no", "n", "off"}:
        return False
    return default


def _audit_model_prompt(*, stage: str, model: str, model_source: str, prompt: str, status: str, route: str) -> None:
    try:
        if os.environ.get("AI_CORE_DISABLE_MODEL_PROMPT_AUDIT", "").lower() in {"1", "true", "yes"}:
            return
        root = _candidate_project_roots()[0] if _candidate_project_roots() else Path.cwd()
        path = root / "runtime" / "logs" / "model_prompt_audit.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        compact = " ".join(str(prompt or "").split())
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "stage_id": str(stage or "general_runtime"),
            "node_id": str(stage or "general_runtime"),
            "route_name": str(route or ""),
            "model": str(model or ""),
            "model_source": str(model_source or ""),
            "prompt_chars": len(str(prompt or "")),
            "prompt_sha256": hashlib.sha256(str(prompt or "").encode("utf-8", errors="ignore")).hexdigest(),
            "prompt_preview": compact[:240],
            "output_status": str(status or ""),
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception:
        return
