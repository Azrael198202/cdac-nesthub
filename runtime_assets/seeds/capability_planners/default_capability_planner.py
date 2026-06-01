from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any


def plan(payload: dict[str, Any]) -> dict[str, Any]:
    """Packaged neutral planner for missing-template acquisition.

    Boundary:
    - This file is a static runtime asset, not ai_core business logic.
    - It contains a generic planning contract and local-model invocation only.
    - It does not embed concrete capability implementations or domain examples.
    """
    request_text = str(payload.get("user_input") or "")
    identity = payload.get("identity_contract") if isinstance(payload.get("identity_contract"), dict) else {}
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
    contract = payload.get("required_template_contract")

    model_payload = _try_model_planner(
        request_text=request_text,
        identity=identity,
        evidence=evidence,
        contract=contract,
    )
    if isinstance(model_payload, dict) and isinstance(model_payload.get("template"), dict):
        model_payload.setdefault("status", "planned")
        model_payload.setdefault("confidence_score", 0.76)
        model_payload.setdefault("needs_external_evidence", False)
        model_payload.setdefault("planner_engine", "local_model")
        return model_payload

    return {
        "status": "planner_failed",
        "reason": "local_model_template_unavailable_or_invalid",
        "confidence_score": 0,
        "needs_external_evidence": True,
        "model_planner_attempt": model_payload if isinstance(model_payload, dict) else {"status": "skipped"},
    }


def _try_model_planner(*, request_text: str, identity: dict[str, Any], evidence: dict[str, Any], contract: Any) -> dict[str, Any]:
    if os.environ.get("AI_CORE_DISABLE_LOCAL_CAPABILITY_MODEL", "").lower() in {"1", "true", "yes"}:
        return {"status": "skipped", "reason": "local_capability_model_disabled"}
    host = os.environ.get("OLLAMA_HOST") or os.environ.get("AI_CORE_OLLAMA_HOST") or "http://127.0.0.1:11434"
    model = os.environ.get("AI_CORE_CAPABILITY_PLANNER_MODEL") or os.environ.get("OLLAMA_MODEL") or "qwen3:8b"
    prompts = [
        _model_prompt(request_text=request_text, identity=identity, evidence=evidence, contract=contract, compact=False),
        _model_prompt(request_text=request_text, identity=identity, evidence=evidence, contract=contract, compact=True),
    ]
    timeout_value = _planner_timeout()
    last_error: dict[str, Any] = {"status": "skipped"}
    for idx, prompt in enumerate(prompts, start=1):
        body = json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0,
                "num_ctx": int(os.environ.get("AI_CORE_CAPABILITY_PLANNER_NUM_CTX", "12288")),
                "num_predict": int(os.environ.get("AI_CORE_CAPABILITY_PLANNER_NUM_PREDICT", "4096")),
            },
        }).encode("utf-8")
        try:
            req = urllib.request.Request(host.rstrip("/") + "/api/generate", data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout_value) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")
            outer = json.loads(raw or "{}")
            text = str(outer.get("response") or "").strip()
            parsed = _parse_json_object(text)
            if not isinstance(parsed, dict):
                last_error = {"status": "planner_failed", "reason": "model_returned_non_json", "attempt": idx, "raw_excerpt": text[:500], "timeout_seconds": timeout_value}
                continue
            template = parsed.get("template") if isinstance(parsed.get("template"), dict) else parsed
            if not isinstance(template, dict):
                last_error = {"status": "planner_failed", "reason": "model_returned_no_template", "attempt": idx, "raw_excerpt": text[:500], "timeout_seconds": timeout_value}
                continue
            return {
                "status": "planned",
                "confidence_score": float(parsed.get("confidence_score") or parsed.get("confidence") or 0.76),
                "needs_external_evidence": _to_bool(parsed.get("needs_external_evidence", False), default=False),
                "template": template,
                "model": model,
                "attempt": idx,
                "timeout_seconds": timeout_value,
            }
        except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
            last_error = {"status": "planner_failed", "reason": f"local_model_unavailable_or_invalid: {exc.__class__.__name__}", "model": model, "attempt": idx, "timeout_seconds": timeout_value}
            continue
        except Exception as exc:
            last_error = {"status": "planner_failed", "reason": f"local_model_error: {exc.__class__.__name__}: {str(exc)[:300]}", "model": model, "attempt": idx, "timeout_seconds": timeout_value}
            continue
    return last_error


def _model_prompt(*, request_text: str, identity: dict[str, Any], evidence: dict[str, Any], contract: Any, compact: bool = False) -> str:
    evidence_text = _evidence_context(evidence, compact=compact)
    base_rules = [
        "Return ONLY valid JSON. No markdown. No explanation outside JSON.",
        "Output object keys: confidence_score, needs_external_evidence, template.",
        "Generate a sandbox-verifiable Python capability template from request plus evidence.",
        "Do not hardcode runtime values, credentials, endpoints, tokens, file paths, or user data.",
        "Declare all runtime values in JSON schemas and read them at execution time.",
        "Use standard library only when the request asks for it; otherwise declare dependencies explicitly.",
        "Template required keys: template_id, description, capabilities, match_terms, entrypoint, files, input_schema, output_schema, connection_schema, secret_schema, approval_policy, runtime_interface, runtime_execution_policy, verification_input, verification_expectations, acquisition_policy, capability_match_contract.",
        "files must include one Python implementation file exposing entrypoint.function and one isolated test file.",
        "Sandbox verification must not contact external services; use a test-mode input.",
        "Live execution must work when the user passes false boolean values for test-mode fields and approval is satisfied.",
        "Generated code must parse boolean form values robustly: true, false, 1, 0, yes, no, on, off.",
        "Generated code must read configuration from top-level connection/secrets and from _runtime.connection/_runtime.secrets.",
        "Use structured errors and provenance-friendly outputs.",
        "If evidence is absent but the request is implementable using stable language or library knowledge, set acquisition_policy.allow_policy_backed_basic_acquisition_without_external_evidence=true.",
    ]
    if compact:
        base_rules.append("Use the shortest correct implementation and compact schemas. Keep generated files concise.")
    return "\n".join([
        "You are a neutral runtime capability template planner.",
        *[f"- {rule}" for rule in base_rules],
        "",
        "Required neutral contract JSON:",
        json.dumps(contract, ensure_ascii=False),
        "",
        "Identity contract JSON:",
        json.dumps(identity, ensure_ascii=False),
        "",
        "Optimized evidence JSON:",
        evidence_text,
        "",
        "User request:",
        request_text,
    ])


def _evidence_context(evidence: dict[str, Any], *, compact: bool) -> str:
    optimized = evidence.get("optimized_evidence") if isinstance(evidence.get("optimized_evidence"), dict) else {}
    evidence_pack = evidence.get("evidence_pack") if isinstance(evidence.get("evidence_pack"), list) else []
    if not evidence_pack and isinstance(optimized.get("evidence_pack"), list):
        evidence_pack = optimized.get("evidence_pack")
    planned_queries = evidence.get("planned_queries") if isinstance(evidence.get("planned_queries"), list) else []
    if not planned_queries and isinstance(optimized.get("planned_queries"), list):
        planned_queries = optimized.get("planned_queries")
    payload = {
        "urls": evidence.get("urls") if isinstance(evidence.get("urls"), list) else [],
        "planned_queries": planned_queries,
        "evidence_pack": evidence_pack,
        "optimizer_summary": optimized.get("summary") if isinstance(optimized.get("summary"), dict) else {},
    }
    limit = 3500 if compact else 9000
    return json.dumps(payload, ensure_ascii=False)[:limit]


def _planner_timeout() -> float | None:
    raw = os.environ.get("AI_CORE_CAPABILITY_PLANNER_TIMEOUT", "600")
    try:
        value = float(raw)
    except Exception:
        value = 600.0
    if value <= 0:
        return None
    return max(30.0, value)


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
