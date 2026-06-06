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
    contract = payload.get("required_template_contract")
    event_contract = payload.get("need_capability_event_contract") if isinstance(payload.get("need_capability_event_contract"), dict) else {}

    model_payload = _try_model_planner(
        request_text=request_text,
        identity=identity,
        evidence=evidence,
        contract=contract,
        event_contract=event_contract,
    )
    if isinstance(model_payload, dict) and (isinstance(model_payload.get("blueprint"), dict) or isinstance(model_payload.get("template"), dict)):
        model_payload.setdefault("status", "planned")
        model_payload.setdefault("confidence_score", 0.76)
        model_payload.setdefault("needs_external_evidence", False)
        model_payload.setdefault("planner_engine", "local_model")
        return model_payload

    fallback_allowed = os.environ.get("AI_CORE_DISABLE_NEUTRAL_BLUEPRINT_FALLBACK", "").lower() not in {"1", "true", "yes"}
    if fallback_allowed:
        return {
            "status": "planned",
            "confidence_score": 0.72,
            "needs_external_evidence": False,
            "planner_engine": "neutral_blueprint_fallback",
            "model_planner_attempt": model_payload if isinstance(model_payload, dict) else {"status": "skipped"},
            "blueprint": _neutral_blueprint(request_text=request_text, identity=identity, event_contract=event_contract),
        }

    return {
        "status": "planner_failed",
        "reason": "local_model_blueprint_unavailable_or_invalid",
        "confidence_score": 0,
        "needs_external_evidence": True,
        "model_planner_attempt": model_payload if isinstance(model_payload, dict) else {"status": "skipped"},
    }


def _try_model_planner(*, request_text: str, identity: dict[str, Any], evidence: dict[str, Any], contract: Any, event_contract: dict[str, Any] | None = None) -> dict[str, Any]:
    if os.environ.get("AI_CORE_DISABLE_LOCAL_CAPABILITY_MODEL", "").lower() in {"1", "true", "yes"}:
        return {"status": "skipped", "reason": "local_capability_model_disabled"}
    host = os.environ.get("OLLAMA_HOST") or os.environ.get("AI_CORE_OLLAMA_HOST") or "http://127.0.0.1:11434"
    model, model_source = _resolve_planner_model()
    attempts = []
    first = _call_ollama_json_planner(
        host=host,
        model=model,
        prompt=_model_prompt(request_text=request_text, identity=identity, evidence=evidence, contract=contract, event_contract=event_contract or {}),
        force_json=True,
        timeout=float(os.environ.get("AI_CORE_CAPABILITY_PLANNER_TIMEOUT", "45")),
    )
    attempts.append(first)
    if isinstance(first.get("blueprint"), dict) or isinstance(first.get("template"), dict):
        return first

    # Small local models sometimes return an empty response when Ollama JSON mode
    # is combined with a long schema prompt. Retry once with a smaller prompt and
    # without provider-side JSON forcing; the parser still accepts only JSON.
    retry = _call_ollama_json_planner(
        host=host,
        model=model,
        prompt=_compact_model_prompt(request_text=request_text, identity=identity, evidence=evidence, contract=contract, event_contract=event_contract or {}),
        force_json=False,
        timeout=float(os.environ.get("AI_CORE_CAPABILITY_PLANNER_COMPACT_TIMEOUT", os.environ.get("AI_CORE_CAPABILITY_PLANNER_TIMEOUT", "45"))),
    )
    attempts.append(retry)
    if isinstance(retry.get("blueprint"), dict) or isinstance(retry.get("template"), dict):
        retry["attempts"] = attempts
        retry["compact_retry_used"] = True
        retry["model_source"] = model_source
        return retry
    return {"status": "planner_failed", "reason": str(retry.get("reason") or first.get("reason") or "model_returned_no_valid_template"), "model": model, "model_source": model_source, "attempts": attempts}


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
        blueprint = parsed.get("blueprint") if isinstance(parsed.get("blueprint"), dict) else parsed.get("template") if isinstance(parsed.get("template"), dict) else parsed
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


def _model_prompt(*, request_text: str, identity: dict[str, Any], evidence: dict[str, Any], contract: Any, event_contract: dict[str, Any] | None = None) -> str:
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
    compact_event_contract = _compact_event_contract(event_contract or {})
    return (
        "You are a runtime capability blueprint planner. Return ONLY one JSON object. "
        "Do not include markdown. Do not ask questions. "
        "Generate a sandbox-verifiable Python capability blueprint from the user request and evidence. "
        "Do not invent fixed runtime values. Do not hardcode endpoints, credentials, addresses, tokens, paths, or user data. "
        "Runtime values must be declared in JSON schemas and supplied at execution time. "
        "Prefer standard library only when requested. External packages must be declared as dependencies. "
        "The JSON object must contain: confidence_score, needs_external_evidence, blueprint. "
        "blueprint must contain: capability_id, description, capabilities, match_terms, entrypoint, files, "
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
        f"Authoritative ai_core contract:\n{json.dumps(compact_event_contract, ensure_ascii=False)}\n\n"
        f"Evidence summary:\n{evidence_text}\n\n"
        f"User request:\n{compact_request}"
    )



def _compact_model_prompt(*, request_text: str, identity: dict[str, Any], evidence: dict[str, Any], contract: Any, event_contract: dict[str, Any] | None = None) -> str:
    optimized = evidence.get("optimized_evidence") if isinstance(evidence.get("optimized_evidence"), dict) else {}
    evidence_pack = []
    if isinstance(evidence.get("evidence_pack"), list):
        evidence_pack = evidence.get("evidence_pack")
    elif isinstance(optimized.get("evidence_pack"), list):
        evidence_pack = optimized.get("evidence_pack")
    minimal_evidence = []
    for item in evidence_pack[:3]:
        if not isinstance(item, dict):
            continue
        minimal_evidence.append({
            "url": item.get("source_url") or item.get("url"),
            "facts": item.get("extracted_facts") or item.get("facts") or item.get("text"),
            "hints": item.get("implementation_hints") or item.get("hints"),
        })
    compact_payload = {
        "identity": identity,
        "request": str(request_text or "")[:900],
        "ai_core_contract": _compact_event_contract(event_contract or {}),
        "evidence": minimal_evidence,
        "contract_keys": list(contract.keys())[:12] if isinstance(contract, dict) else [],
    }
    return (
        "Return ONLY valid JSON. No markdown. No explanation. "
        "Create one runtime capability blueprint. "
        "Do not hardcode runtime values. Put runtime values in schemas. "
        "Use only neutral generic structure. "
        "Required shape: {\"confidence_score\":0.0-1.0,\"needs_external_evidence\":false,\"template\":{...}}. "
        "The template must include template_id, description, capabilities, match_terms, entrypoint, files, "
        "input_schema, output_schema, connection_schema, secret_schema, approval_policy, runtime_interface, "
        "runtime_execution_policy, verification_input, verification_expectations, acquisition_policy, capability_match_contract. "
        "files must include one Python implementation and one isolated unit test. "
        "Sandbox verification must not call external services. "
        "Boolean form values may arrive as strings and must be parsed robustly.\n"
        f"DATA={json.dumps(compact_payload, ensure_ascii=False)}"
    )



def _neutral_blueprint(*, request_text: str, identity: dict[str, Any], event_contract: dict[str, Any] | None = None) -> dict[str, Any]:
    requested = str(identity.get("requested_capability_id") or "").strip()
    if not requested:
        match = re.search(r"Acquire\s+runtime\s+capability\s*:\s*\n?\s*([^\n.]+)", request_text, flags=re.I)
        requested = _safe_name(match.group(1)) if match else "generated_capability"
    return {
        "capability_id": _safe_name(requested),
        "description": "Neutral runtime-generated capability blueprint created without embedded domain behavior.",
        "capabilities": [_safe_name(requested)],
        "match_terms": [],
        "entrypoint": {"module": "tool.py", "function": "run"},
        "input_schema": _schema_from_event_contract(event_contract or {}),
        "output_schema": {"type": "object", "properties": {"status": {"type": "string"}, "data": {"type": "object"}}, "additionalProperties": True},
        "verification_input": {"_runtime": {"dry_run": True}},
        "verification_expectations": {"status": "completed"},
        "acquisition_policy": {"allow_policy_backed_basic_acquisition_without_external_evidence": True},
        "capability_match_contract": {
            "expected_tool_id": _safe_name(requested),
            "expected_template_id": _safe_name(requested),
            "required_artifact_dir_name": _safe_name(requested),
            "required_markers": [_safe_name(requested)],
            "forbidden_markers": [],
        },
    }


def _schema_from_event_contract(event_contract: dict[str, Any]) -> dict[str, Any]:
    workflow = event_contract.get("workflow_contract") if isinstance(event_contract.get("workflow_contract"), dict) else {}
    known = workflow.get("known_parameters") if isinstance(workflow.get("known_parameters"), dict) else {}
    properties: dict[str, Any] = {}
    for key, value in known.items():
        name = _safe_name(str(key))
        if not name:
            continue
        typ = "boolean" if isinstance(value, bool) else "number" if isinstance(value, (int, float)) else "array" if isinstance(value, list) else "object" if isinstance(value, dict) else "string"
        properties[name] = {"type": typ}
    # If ai_core has no concrete runtime-value contract yet, keep this blueprint
    # non-registerable by using an open schema; the registration gate will block it.
    if not properties:
        return {"type": "object", "additionalProperties": True}
    return {"type": "object", "properties": properties, "required": list(properties.keys()), "additionalProperties": False}


def _compact_event_contract(event_contract: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(event_contract, dict):
        return {}
    workflow = event_contract.get("workflow_contract") if isinstance(event_contract.get("workflow_contract"), dict) else {}
    intent = event_contract.get("intent_contract") if isinstance(event_contract.get("intent_contract"), dict) else {}
    input_contract = event_contract.get("input_contract") if isinstance(event_contract.get("input_contract"), dict) else {}
    return {
        "contract_version": event_contract.get("contract_version"),
        "intent_contract": {
            "intent_type": intent.get("intent_type"),
            "response_mode": intent.get("response_mode"),
            "required_capabilities": intent.get("required_capabilities"),
            "capability_acquisition_policy": intent.get("capability_acquisition_policy"),
        },
        "workflow_contract": {
            "planned_step": workflow.get("planned_step"),
            "known_parameters": workflow.get("known_parameters"),
            "blocking_missing_information": workflow.get("blocking_missing_information"),
            "locked_execution": workflow.get("locked_execution"),
        },
        "capability_constraints": event_contract.get("capability_constraints"),
        "input_contract": {"explicit_constraints": input_contract.get("explicit_constraints")},
        "acquisition_boundary": event_contract.get("acquisition_boundary"),
    }


def _safe_name(value: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in str(value)).strip("_").lower() or "generated_capability"

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
