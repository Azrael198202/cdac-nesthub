from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any


def plan(payload: dict[str, Any]) -> dict[str, Any]:
    """Runtime-owned default capability planner.

    Contract:
    - ai_core calls this hook only when TemplateResolver cannot find a template.
    - This runtime artifact may use a local model to synthesize a template.
    - If the model is unavailable or returns invalid JSON, a guarded fallback may
      create a basic, standard-library-only template when the request is simple
      and sandbox-verifiable.
    """
    user_input = str(payload.get("user_input") or "")
    identity = payload.get("identity_contract") if isinstance(payload.get("identity_contract"), dict) else {}
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}

    model_payload = _try_model_planner(user_input=user_input, identity=identity, evidence=evidence, contract=payload.get("required_template_contract"))
    if isinstance(model_payload, dict) and isinstance(model_payload.get("template"), dict):
        model_payload.setdefault("status", "planned")
        model_payload.setdefault("confidence_score", 0.78)
        model_payload.setdefault("needs_external_evidence", False)
        model_payload.setdefault("planner_engine", "local_model")
        return model_payload

    fallback = _guarded_standard_library_fallback(user_input=user_input, identity=identity)
    if fallback:
        fallback["model_planner_attempt"] = model_payload if isinstance(model_payload, dict) else {"status": "skipped"}
        return fallback

    return {
        "status": "planner_failed",
        "reason": "no_model_template_and_no_guarded_fallback_matched",
        "confidence_score": 0,
        "needs_external_evidence": True,
        "model_planner_attempt": model_payload if isinstance(model_payload, dict) else {"status": "skipped"},
    }


def _try_model_planner(*, user_input: str, identity: dict[str, Any], evidence: dict[str, Any], contract: Any) -> dict[str, Any]:
    if os.environ.get("AI_CORE_DISABLE_LOCAL_CAPABILITY_MODEL", "").lower() in {"1", "true", "yes"}:
        return {"status": "skipped", "reason": "local_capability_model_disabled"}
    host = os.environ.get("OLLAMA_HOST") or os.environ.get("AI_CORE_OLLAMA_HOST") or "http://127.0.0.1:11434"
    model = os.environ.get("AI_CORE_CAPABILITY_PLANNER_MODEL") or os.environ.get("OLLAMA_MODEL") or "qwen3:8b"
    prompt = _model_prompt(user_input=user_input, identity=identity, evidence=evidence, contract=contract)
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1, "num_ctx": 8192},
    }).encode("utf-8")
    try:
        req = urllib.request.Request(host.rstrip("/") + "/api/generate", data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=float(os.environ.get("AI_CORE_CAPABILITY_PLANNER_TIMEOUT", "90"))) as resp:
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
            "needs_external_evidence": bool(parsed.get("needs_external_evidence", False)),
            "template": template,
            "model": model,
        }
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return {"status": "planner_failed", "reason": f"local_model_unavailable_or_invalid: {exc.__class__.__name__}", "model": model}
    except Exception as exc:
        return {"status": "planner_failed", "reason": f"local_model_error: {exc.__class__.__name__}: {str(exc)[:300]}", "model": model}


def _model_prompt(*, user_input: str, identity: dict[str, Any], evidence: dict[str, Any], contract: Any) -> str:
    evidence_text = json.dumps({
        "urls": evidence.get("urls") if isinstance(evidence.get("urls"), list) else [],
        "results": evidence.get("results") if isinstance(evidence.get("results"), list) else [],
    }, ensure_ascii=False)[:4000]
    return (
        "You are a runtime capability template planner. Return ONLY one JSON object. "
        "Do not include markdown. Do not ask questions. Generate a sandbox-verifiable Python capability template. "
        "Do not require external packages when the user requests standard library. "
        "The JSON object must have keys: confidence_score, needs_external_evidence, template. "
        "template must include: template_id, description, capabilities, match_terms, entrypoint, files, "
        "input_schema, output_schema, connection_schema, secret_schema, approval_policy, runtime_interface, "
        "runtime_execution_policy, verification_input, verification_expectations, acquisition_policy, capability_match_contract. "
        "files must contain a Python implementation file and a test file. The implementation must expose the entrypoint function. "
        "Runtime values must be represented in connection_schema and secret_schema, not hardcoded. "
        "Verification must use dry-run or mock behavior and must not contact external services.\n\n"
        f"Required neutral contract:\n{json.dumps(contract, ensure_ascii=False)}\n\n"
        f"Identity contract:\n{json.dumps(identity, ensure_ascii=False)}\n\n"
        f"Evidence summary:\n{evidence_text}\n\n"
        f"User request:\n{user_input}"
    )


def _guarded_standard_library_fallback(*, user_input: str, identity: dict[str, Any]) -> dict[str, Any] | None:
    folded = user_input.casefold()
    # Guarded fallback is intentionally narrow and runtime-owned. It exists so a
    # basic standard-library request can still be validated when the local model
    # or web retrieval is unavailable. ai_core remains generic and only loads the
    # planner contract.
    if not ("smtp" in folded and ("mail" in folded or "email" in folded or "sender" in folded)):
        return None
    if not ("standard library" in folded or "smtplib" in folded or "email.message" in folded or "no external package" in folded):
        return None
    tool_id = _safe_name(str(identity.get("requested_capability_id") or "basic_smtp_mail_sender"))
    template = _basic_smtp_mail_sender_template(tool_id)
    return {
        "status": "planned",
        "confidence_score": 0.82,
        "needs_external_evidence": False,
        "planner_engine": "guarded_standard_library_fallback",
        "template": template,
    }


def _basic_smtp_mail_sender_template(tool_id: str) -> dict[str, Any]:
    implementation = r'''from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Any


def run(payload: dict[str, Any]) -> dict[str, Any]:
    payload = payload or {}
    message_data = payload.get("input") if isinstance(payload.get("input"), dict) else payload
    connection = payload.get("connection") if isinstance(payload.get("connection"), dict) else {}
    secrets = payload.get("secrets") if isinstance(payload.get("secrets"), dict) else {}

    to_addresses = message_data.get("to") or []
    if isinstance(to_addresses, str):
        to_addresses = [to_addresses]
    to_addresses = [str(item).strip() for item in to_addresses if str(item).strip()]
    subject = str(message_data.get("subject") or "")
    body = str(message_data.get("body") or "")
    from_address = str(message_data.get("from_address") or connection.get("from_address") or "")
    dry_run = bool(message_data.get("dry_run", True))
    mock = bool(message_data.get("mock", dry_run))

    if not to_addresses:
        return {"status": "failed", "reason": "missing_recipient"}
    if not from_address:
        return {"status": "failed", "reason": "missing_from_address"}

    msg = EmailMessage()
    msg["From"] = from_address
    msg["To"] = ", ".join(to_addresses)
    msg["Subject"] = subject
    msg.set_content(body)

    if dry_run or mock:
        return {
            "status": "completed",
            "data": {
                "dry_run": True,
                "mock": True,
                "transport": "smtplib",
                "message_library": "email.message",
                "recipient_count": len(to_addresses),
                "subject": subject,
            },
        }

    host = str(connection.get("host") or "")
    port = int(connection.get("port") or 587)
    username = str(connection.get("username") or "")
    password = str(secrets.get("password") or "")
    timeout = float(connection.get("timeout_seconds") or 30)
    use_ssl = bool(connection.get("use_ssl", False))
    use_tls = bool(connection.get("use_tls", True))

    if not host:
        return {"status": "failed", "reason": "missing_smtp_host"}

    smtp_cls = smtplib.SMTP_SSL if use_ssl else smtplib.SMTP
    with smtp_cls(host, port, timeout=timeout) as client:
        if use_tls and not use_ssl:
            client.starttls()
        if username:
            client.login(username, password)
        client.send_message(msg)

    return {"status": "completed", "data": {"sent": True, "recipient_count": len(to_addresses)}}
'''
    test_code = r'''from tool import run


def test_mock_send():
    result = run({
        "input": {
            "to": ["recipient@example.com"],
            "from_address": "sender@example.com",
            "subject": "Sandbox verification",
            "body": "This is a mock message.",
            "dry_run": True,
            "mock": True,
        },
        "connection": {"host": "smtp.example.com", "port": 587, "use_tls": True},
        "secrets": {"password": "not-used-in-mock"},
    })
    assert result["status"] == "completed"
    assert result["data"]["dry_run"] is True
    assert result["data"]["transport"] == "smtplib"


if __name__ == "__main__":
    test_mock_send()
'''
    return {
        "template_id": tool_id,
        "description": "Runtime-generated basic SMTP mail sender using Python standard library dry-run verification.",
        "capabilities": [tool_id, "send_message_via_configured_transport"],
        "match_terms": ["smtp", "mail", "sender", "standard library", "smtplib", "email.message"],
        "required_terms": [],
        "selection_priority": 0,
        "entrypoint": {"module": "tool.py", "function": "run"},
        "dependencies": [],
        "files": [
            {"path": "tool.py", "content": implementation},
            {"path": "test_tool.py", "content": test_code},
        ],
        "input_schema": {
            "type": "object",
            "required": ["to", "from_address", "subject", "body"],
            "properties": {
                "to": {"type": "array", "items": {"type": "string"}},
                "from_address": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "dry_run": {"type": "boolean", "default": True},
                "mock": {"type": "boolean", "default": True},
            },
            "additionalProperties": True,
        },
        "output_schema": {
            "type": "object",
            "required": ["status"],
            "properties": {"status": {"type": "string"}, "data": {"type": "object"}, "reason": {"type": "string"}},
            "additionalProperties": True,
        },
        "connection_schema": {
            "type": "object",
            "required": ["host", "port", "from_address"],
            "properties": {
                "host": {"type": "string", "title": "SMTP host"},
                "port": {"type": "integer", "default": 587},
                "from_address": {"type": "string"},
                "username": {"type": "string"},
                "use_tls": {"type": "boolean", "default": True},
                "use_ssl": {"type": "boolean", "default": False},
                "timeout_seconds": {"type": "number", "default": 30},
            },
            "additionalProperties": False,
        },
        "secret_schema": {
            "type": "object",
            "properties": {"password": {"type": "string", "writeOnly": True}},
            "additionalProperties": False,
        },
        "approval_policy": {
            "required": True,
            "preview_fields": ["to", "subject", "from_address"],
            "reason": "Outbound message sending requires user approval before live execution.",
        },
        "runtime_interface": {
            "configuration_values": "agent_studio_profile_form",
            "secret_values": "local_runtime_secret_store",
            "supports_dry_run": True,
        },
        "runtime_execution_policy": {
            "default_mode": "dry_run",
            "live_execution_requires_approval": True,
            "no_external_packages": True,
        },
        "verification_input": {
            "input": {
                "to": ["recipient@example.com"],
                "from_address": "sender@example.com",
                "subject": "Sandbox verification",
                "body": "mock body",
                "dry_run": True,
                "mock": True,
            },
            "connection": {"host": "smtp.example.com", "port": 587, "from_address": "sender@example.com"},
            "secrets": {"password": "not-used"},
        },
        "verification_expectations": {"status": "completed", "dry_run": True},
        "acquisition_policy": {
            "allow_policy_backed_basic_acquisition_without_external_evidence": True,
            "external_evidence_required_when_model_confidence_below": 0.7,
        },
        "capability_match_contract": {
            "expected_tool_id": tool_id,
            "expected_template_id": tool_id,
            "required_artifact_dir_name": tool_id,
            "required_markers": ["smtplib", "EmailMessage", "dry_run", "mock"],
            "forbidden_markers": ["requests", "boto3", "sendgrid"],
        },
    }


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


def _safe_name(value: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in value).strip("_").lower() or "generated_capability"
