from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
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
    model = os.environ.get("AI_CORE_CAPABILITY_PLANNER_MODEL") or os.environ.get("OLLAMA_MODEL") or "qwen3.5:2b"
    prompt = _model_prompt(request_text=request_text, identity=identity, evidence=evidence, contract=contract)
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0, "num_ctx": int(os.environ.get("AI_CORE_CAPABILITY_PLANNER_NUM_CTX", "4096")), "num_predict": int(os.environ.get("AI_CORE_CAPABILITY_PLANNER_NUM_PREDICT", "2048")), "think": False},
    }).encode("utf-8")
    try:
        req = urllib.request.Request(host.rstrip("/") + "/api/generate", data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=float(os.environ.get("AI_CORE_CAPABILITY_PLANNER_TIMEOUT", "45"))) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        outer = json.loads(raw or "{}")
        text = str(outer.get("response") or "").strip()
        parsed = _parse_json_object(text)
        if not isinstance(parsed, dict):
            return {"status": "planner_failed", "reason": "model_returned_non_json", "raw_excerpt": text[:500]}
        template = parsed.get("template") if isinstance(parsed.get("template"), dict) else parsed
        if not isinstance(template, dict):
            return {"status": "planner_failed", "reason": "model_returned_no_template", "raw_excerpt": text[:500]}
        return {
            "status": "planned",
            "confidence_score": float(parsed.get("confidence_score") or parsed.get("confidence") or 0.76),
            "needs_external_evidence": _to_bool(parsed.get("needs_external_evidence", False), default=False),
            "template": template,
            "model": model,
        }
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return {"status": "planner_failed", "reason": f"local_model_unavailable_or_invalid: {exc.__class__.__name__}", "model": model}
    except Exception as exc:
        return {"status": "planner_failed", "reason": f"local_model_error: {exc.__class__.__name__}: {str(exc)[:300]}", "model": model}


def _model_prompt(*, request_text: str, identity: dict[str, Any], evidence: dict[str, Any], contract: Any) -> str:
    optimized = evidence.get("optimized_evidence") if isinstance(evidence.get("optimized_evidence"), dict) else {}
    evidence_pack = []
    if isinstance(evidence.get("evidence_pack"), list):
        evidence_pack = evidence.get("evidence_pack")
    elif isinstance(optimized.get("evidence_pack"), list):
        evidence_pack = optimized.get("evidence_pack")
    evidence_text = json.dumps({
        "urls": (evidence.get("urls") if isinstance(evidence.get("urls"), list) else [])[:5],
        "evidence_pack": evidence_pack[:6],
        "trusted_summary": optimized.get("summary") if isinstance(optimized, dict) else None,
    }, ensure_ascii=False)[:2200]
    compact_request = str(request_text or "")[:1600]
    compact_contract = _compact_contract(contract)
    return (
        "You are a runtime capability template planner. Return ONLY one JSON object. "
        "Do not include markdown. Do not ask questions. "
        "Generate a sandbox-verifiable Python capability template from the user request and evidence. "
        "Do not invent fixed runtime values. Do not hardcode endpoints, credentials, addresses, tokens, paths, or user data. "
        "Runtime values must be declared in JSON schemas and supplied at execution time. "
        "Prefer standard library only when requested. External packages must be declared as dependencies. "
        "The JSON object must contain: confidence_score, needs_external_evidence, template. "
        "template must contain: template_id, description, capabilities, match_terms, entrypoint, files, "
        "input_schema, output_schema, connection_schema, secret_schema, approval_policy, runtime_interface, "
        "runtime_execution_policy, verification_input, verification_expectations, acquisition_policy, capability_match_contract. "
        "files must contain one Python implementation file exposing the entrypoint function and one isolated test file. "
        "Sandbox verification must not contact external services and must use declared test-mode input. "
        "Live execution must be possible when the user passes false boolean values for test-mode fields and confirms approval. "
        "Generated Python must parse booleans robustly because browser forms may pass strings such as true, false, 1, 0, yes, no. "
        "Generated code should also accept runtime configuration from either top-level connection/secrets objects or _runtime.connection/_runtime.secrets. "
        "Use neutral validation, structured errors, and provenance-friendly outputs.\n\n"
        f"Required neutral contract:\n{json.dumps(compact_contract, ensure_ascii=False)}\n\n"
        f"Identity contract:\n{json.dumps(identity, ensure_ascii=False)}\n\n"
        f"Evidence summary:\n{evidence_text}\n\n"
        f"User request:\n{compact_request}"
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
