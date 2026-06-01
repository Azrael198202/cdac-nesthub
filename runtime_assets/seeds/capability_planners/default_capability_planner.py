from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
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

    return {
        "status": "planner_failed",
        "reason": "local_model_blueprint_unavailable_or_invalid",
        "confidence_score": 0,
        "needs_external_evidence": True,
        "model_planner_attempt": model_payload if isinstance(model_payload, dict) else {"status": "skipped"},
    }


def _try_model_planner(*, request_text: str, identity: dict[str, Any], evidence: dict[str, Any], contract: Any) -> dict[str, Any]:
    if os.environ.get("AI_CORE_DISABLE_LOCAL_CAPABILITY_MODEL", "").lower() in {"1", "true", "yes"}:
        return {"status": "skipped", "reason": "local_capability_model_disabled"}
    host = os.environ.get("OLLAMA_HOST") or os.environ.get("AI_CORE_OLLAMA_HOST") or "http://127.0.0.1:11434"
    model, model_source = _resolve_planner_model()
    attempts = []
    first = _call_ollama_json_planner(
        host=host,
        model=model,
        prompt=_model_prompt(request_text=request_text, identity=identity, evidence=evidence, contract=contract),
        force_json=True,
        timeout=float(os.environ.get("AI_CORE_CAPABILITY_PLANNER_TIMEOUT", "45")),
    )
    attempts.append(first)
    if isinstance(first.get("blueprint"), dict):
        return first

    # Small local models sometimes return an empty response when Ollama JSON mode
    # is combined with a long schema prompt. Retry once with a smaller prompt and
    # without provider-side JSON forcing; the parser still accepts only JSON.
    retry = _call_ollama_json_planner(
        host=host,
        model=model,
        prompt=_compact_model_prompt(request_text=request_text, identity=identity, evidence=evidence, contract=contract),
        force_json=False,
        timeout=float(os.environ.get("AI_CORE_CAPABILITY_PLANNER_COMPACT_TIMEOUT", os.environ.get("AI_CORE_CAPABILITY_PLANNER_TIMEOUT", "45"))),
    )
    attempts.append(retry)
    if isinstance(retry.get("blueprint"), dict):
        retry["attempts"] = attempts
        retry["compact_retry_used"] = True
        retry["model_source"] = model_source
        return retry
    return {"status": "planner_failed", "reason": str(retry.get("reason") or first.get("reason") or "model_returned_no_valid_blueprint"), "model": model, "model_source": model_source, "attempts": attempts}


def _resolve_planner_model() -> tuple[str, str]:
    """Resolve the local planner model from runtime selection before defaults.

    The runtime UI writes the selected model under configs/model_selection.json.
    The planner must honor that value; otherwise Agent Studio may show one model
    while the capability planner silently uses another. Environment variables keep
    highest priority for headless/server deployments.
    """
    env_model = (os.environ.get("AI_CORE_CAPABILITY_PLANNER_MODEL") or os.environ.get("OLLAMA_MODEL") or "").strip()
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
        selected = str(data.get("selected_local_model_id") or data.get("initial_model_id") or "").strip()
        mode = str(data.get("mode") or "").strip().casefold()
        if selected and mode in {"", "local_only", "hybrid", "local_first"}:
            return selected, "configs/model_selection.json"
    return "qwen3.5:2b", "default"


def _candidate_project_roots() -> list[Path]:
    roots: list[Path] = []
    try:
        # runtime_assets/seeds/capability_planners/default_capability_planner.py
        roots.append(Path(__file__).resolve().parents[3])
    except Exception:
        pass
    try:
        roots.append(Path.cwd().resolve())
    except Exception:
        pass
    unique: list[Path] = []
    for root in roots:
        if root not in unique:
            unique.append(root)
    return unique


def _call_ollama_json_planner(*, host: str, model: str, prompt: str, force_json: bool, timeout: float) -> dict[str, Any]:
    body_payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0, "num_ctx": int(os.environ.get("AI_CORE_CAPABILITY_PLANNER_NUM_CTX", "3072")), "num_predict": int(os.environ.get("AI_CORE_CAPABILITY_PLANNER_NUM_PREDICT", "1600")), "think": False},
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
            return {"status": "planner_failed", "reason": "model_returned_non_json", "raw_excerpt": text[:500], "model": model, "force_json": force_json}
        blueprint = parsed.get("blueprint") if isinstance(parsed.get("blueprint"), dict) else parsed
        if not isinstance(blueprint, dict):
            return {"status": "planner_failed", "reason": "model_returned_no_blueprint", "raw_excerpt": text[:500], "model": model, "force_json": force_json}
        return {
            "status": "planned",
            "confidence_score": float(parsed.get("confidence_score") or parsed.get("confidence") or 0.76),
            "needs_external_evidence": _to_bool(parsed.get("needs_external_evidence", False), default=False),
            "blueprint": blueprint,
            "model": model,
            "force_json": force_json,
        }
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return {"status": "planner_failed", "reason": f"local_model_unavailable_or_invalid: {exc.__class__.__name__}", "model": model, "force_json": force_json}
    except Exception as exc:
        return {"status": "planner_failed", "reason": f"local_model_error: {exc.__class__.__name__}: {str(exc)[:300]}", "model": model, "force_json": force_json}


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
