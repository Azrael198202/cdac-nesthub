from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


class RuntimeBlueprintArtifactGenerator:
    """Materialize runtime capability blueprints into sandboxable artifacts.

    Boundary:
    - This module is in auxiliary_brain, not ai_core.
    - It does not decide user intent.
    - It never reuses a previous capability artifact.
    - It supports a generic runtime-native path for basic standard-library
      capabilities when no external evidence is required.
    """

    def materialize(self, blueprint: dict[str, Any], *, identity_contract: dict[str, Any] | None = None) -> dict[str, Any]:
        if not isinstance(blueprint, dict):
            blueprint = {}
        identity_contract = identity_contract or {}
        tool_id = self._safe_name(str(
            blueprint.get("capability_id")
            or blueprint.get("tool_id")
            or blueprint.get("template_id")
            or identity_contract.get("requested_capability_id")
            or "generated_capability"
        ))
        entrypoint = blueprint.get("entrypoint") if isinstance(blueprint.get("entrypoint"), dict) else {"module": "tool.py", "function": "run"}
        entrypoint.setdefault("module", "tool.py")
        entrypoint.setdefault("function", "run")

        if self._looks_like_basic_smtp_request(blueprint, identity_contract):
            files = self._smtp_files(tool_id=tool_id, entrypoint=entrypoint)
            input_schema, output_schema, connection_schema, secret_schema = self._smtp_schemas()
            verification_input = self._smtp_verification_input()
            verification_expectations = {"status": "completed"}
            capability_contract = {
                "expected_tool_id": tool_id,
                "expected_template_id": tool_id,
                "required_artifact_dir_name": tool_id,
                "required_markers": ["smtplib", "EmailMessage", "send_message", "input_schema", "connection_schema", "secret_schema"],
                "forbidden_markers": ["requires_runtime_implementation", "Runtime blueprint artifact verified", "Blueprint only"],
            }
            artifact_kind = "real_runtime_implementation"
        else:
            input_schema = self._schema_or_default(blueprint.get("input_schema"), "input")
            output_schema = self._schema_or_default(blueprint.get("output_schema"), "output")
            connection_schema = self._closed_schema(blueprint.get("connection_schema"))
            secret_schema = self._closed_schema(blueprint.get("secret_schema"))
            verification_expectations = blueprint.get("verification_expectations") if isinstance(blueprint.get("verification_expectations"), dict) else {"status": "completed"}
            capability_contract = blueprint.get("capability_match_contract") if isinstance(blueprint.get("capability_match_contract"), dict) else {
                "expected_tool_id": tool_id,
                "expected_template_id": tool_id,
                "required_artifact_dir_name": tool_id,
                "required_markers": [tool_id, "TOOL_ID", "run"],
                "forbidden_markers": ["requires_runtime_implementation", "Runtime blueprint artifact verified", "Blueprint only"],
            }
            files = blueprint.get("files") if isinstance(blueprint.get("files"), list) else []
            if self._valid_files(files) and not self._files_look_like_stub(files):
                verification_input = blueprint.get("verification_input") if isinstance(blueprint.get("verification_input"), dict) else self._generic_verification_input(input_schema)
                artifact_kind = "real_runtime_implementation"
            elif self._allows_runtime_native_materialization(blueprint, identity_contract):
                files = self._generic_stateful_files(tool_id=tool_id, entrypoint=entrypoint, input_schema=input_schema)
                verification_input = self._generic_verification_input(input_schema)
                verification_expectations = {"status": "completed"}
                capability_contract = {
                    **capability_contract,
                    "expected_tool_id": tool_id,
                    "expected_template_id": tool_id,
                    "required_artifact_dir_name": tool_id,
                    "required_markers": [tool_id, "TOOL_ID", "json", "Path", "operation"],
                    "forbidden_markers": ["requires_runtime_implementation", "Runtime blueprint artifact verified", "Blueprint only"],
                }
                artifact_kind = "real_runtime_implementation"
            else:
                files = self._neutral_files(tool_id=tool_id, entrypoint=entrypoint)
                verification_input = blueprint.get("verification_input") if isinstance(blueprint.get("verification_input"), dict) else {"_runtime": {"dry_run": True}}
                artifact_kind = "blueprint_only_not_registerable"

        return {
            "template_id": tool_id,
            "description": str(blueprint.get("description") or "Runtime-generated capability artifact."),
            "capabilities": blueprint.get("capabilities") if isinstance(blueprint.get("capabilities"), list) else [tool_id],
            "match_terms": blueprint.get("match_terms") if isinstance(blueprint.get("match_terms"), list) else [],
            "required_terms": blueprint.get("required_terms") if isinstance(blueprint.get("required_terms"), list) else [],
            "entrypoint": entrypoint,
            "files": files,
            "input_schema": input_schema,
            "output_schema": output_schema,
            "connection_schema": connection_schema,
            "secret_schema": secret_schema,
            "approval_policy": blueprint.get("approval_policy") if isinstance(blueprint.get("approval_policy"), dict) else {"mode": "required_for_side_effects", "preview_required": True},
            "runtime_interface": blueprint.get("runtime_interface") if isinstance(blueprint.get("runtime_interface"), dict) else {"input_mode": "json", "output_mode": "json"},
            "runtime_execution_policy": blueprint.get("runtime_execution_policy") if isinstance(blueprint.get("runtime_execution_policy"), dict) else {"side_effects": "runtime_declared"},
            "verification_input": verification_input,
            "verification_expectations": verification_expectations,
            "acquisition_policy": blueprint.get("acquisition_policy") if isinstance(blueprint.get("acquisition_policy"), dict) else {"allow_policy_backed_basic_acquisition_without_external_evidence": True},
            "capability_match_contract": capability_contract,
            "artifact_kind": artifact_kind,
            "blueprint_source": blueprint.get("blueprint_source") or "runtime_blueprint_planner",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _looks_like_basic_smtp_request(self, blueprint: dict[str, Any], identity_contract: dict[str, Any]) -> bool:
        text = json.dumps({"blueprint": blueprint, "identity": identity_contract}, ensure_ascii=False).casefold()
        return "smtp" in text and any(token in text for token in ["mail", "email", "sender", "send"])

    def _smtp_schemas(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        input_schema = {
            "type": "object", "required": ["to", "subject", "body"],
            "properties": {
                "to": {"type": "array", "items": {"type": "string", "format": "email", "minLength": 3}, "minItems": 1},
                "cc": {"type": "array", "items": {"type": "string", "format": "email"}, "default": []},
                "bcc": {"type": "array", "items": {"type": "string", "format": "email"}, "default": []},
                "subject": {"type": "string", "minLength": 1},
                "body": {"type": "string", "minLength": 1},
                "body_subtype": {"type": "string", "enum": ["plain", "html"], "default": "plain"},
                "from_email": {"type": "string", "format": "email", "minLength": 3},
                "reply_to": {"type": "string", "format": "email"},
                "dry_run": {"type": "boolean", "default": False},
            },
            "additionalProperties": False,
        }
        output_schema = {
            "type": "object", "required": ["status", "data"],
            "properties": {"status": {"type": "string"}, "data": {"type": "object"}, "message": {"type": "string"}, "provenance": {"type": "object"}},
            "additionalProperties": False,
        }
        connection_schema = {
            "type": "object", "required": ["smtp_host", "smtp_port"],
            "properties": {
                "smtp_host": {"type": "string", "minLength": 1},
                "smtp_port": {"type": "integer", "minimum": 1, "maximum": 65535},
                "use_tls": {"type": "boolean", "default": True},
                "starttls": {"type": "boolean", "default": False},
                "timeout_seconds": {"type": "number", "minimum": 1, "maximum": 120, "default": 20},
                "default_from_email": {"type": "string", "format": "email"},
            },
            "additionalProperties": False,
        }
        secret_schema = {
            "type": "object", "required": [],
            "properties": {"username": {"type": "string", "format": "email"}, "password": {"type": "string", "format": "password"}},
            "additionalProperties": False,
        }
        return input_schema, output_schema, connection_schema, secret_schema

    def _smtp_verification_input(self) -> dict[str, Any]:
        return {
            "dry_run": True,
            "input": {"to": ["recipient@example.invalid"], "subject": "Capability verification", "body": "Dry-run verification message.", "from_email": "sender@example.invalid", "dry_run": True},
            "connection": {"smtp_host": "mock.smtp.invalid", "smtp_port": 587, "use_tls": False, "starttls": True, "timeout_seconds": 5},
            "secrets": {"username": "dry-run-user", "password": "dry-run-password"},
            "_runtime": {"dry_run": True},
        }

    def _smtp_files(self, *, tool_id: str, entrypoint: dict[str, Any]) -> list[dict[str, str]]:
        module = str(entrypoint.get("module") or "tool.py")
        function = str(entrypoint.get("function") or "run")
        verification_input_repr = repr(self._smtp_verification_input())
        code = f'''from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Any

TOOL_ID = {tool_id!r}


class _DryRunSMTP:
    def __init__(self, host: str, port: int, timeout: float | None = None) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.messages: list[EmailMessage] = []
        self.started_tls = False
        self.logged_in = False

    def __enter__(self) -> "_DryRunSMTP":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.quit()

    def starttls(self) -> None:
        self.started_tls = True

    def login(self, username: str, password: str) -> None:
        self.logged_in = bool(username or password)

    def send_message(self, message: EmailMessage) -> dict[str, Any]:
        self.messages.append(message)
        return {{}}

    def quit(self) -> None:
        return None


def _as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {{}}


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().casefold()
    if text in {{"true", "1", "yes", "y", "on"}}:
        return True
    if text in {{"false", "0", "no", "n", "off"}}:
        return False
    return default


def _as_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _first_present(*values: Any, default: Any = None) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return default


def _build_message(runtime_input: dict[str, Any], connection: dict[str, Any]) -> EmailMessage:
    to_values = _as_list(runtime_input.get("to"))
    subject = str(runtime_input.get("subject") or "").strip()
    body = str(runtime_input.get("body") or "")
    from_email = str(_first_present(runtime_input.get("from_email"), connection.get("default_from_email"), default="")).strip()
    if not to_values:
        raise ValueError("input.to is required")
    if not subject:
        raise ValueError("input.subject is required")
    if not body:
        raise ValueError("input.body is required")
    if not from_email:
        raise ValueError("input.from_email or connection.default_from_email is required")
    message = EmailMessage()
    message["From"] = from_email
    message["To"] = ", ".join(to_values)
    cc_values = _as_list(runtime_input.get("cc"))
    if cc_values:
        message["Cc"] = ", ".join(cc_values)
    reply_to = str(runtime_input.get("reply_to") or "").strip()
    if reply_to:
        message["Reply-To"] = reply_to
    message["Subject"] = subject
    subtype = str(runtime_input.get("body_subtype") or "plain").strip().lower()
    if subtype not in {{"plain", "html"}}:
        subtype = "plain"
    message.set_content(body, subtype=subtype)
    return message


def {function}(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = _as_mapping(payload)
    runtime = _as_mapping(payload.get("_runtime"))
    runtime_input = _as_mapping(payload.get("input") or payload.get("runtime_input") or payload.get("parameters") or payload)
    connection = _as_mapping(payload.get("connection") or payload.get("profile") or payload.get("runtime_connection") or runtime.get("connection"))
    secrets = _as_mapping(payload.get("secrets") or payload.get("secret") or payload.get("runtime_secrets") or runtime.get("secrets"))
    dry_run = _as_bool(_first_present(runtime_input.get("dry_run"), payload.get("dry_run"), runtime.get("dry_run"), default=False), default=False)
    host = str(connection.get("smtp_host") or "").strip()
    port = int(connection.get("smtp_port") or 0)
    timeout = float(connection.get("timeout_seconds") or 20)
    if not host:
        raise ValueError("connection.smtp_host is required")
    if port <= 0 or port > 65535:
        raise ValueError("connection.smtp_port must be between 1 and 65535")
    message = _build_message(runtime_input, connection)
    recipients = _as_list(runtime_input.get("to")) + _as_list(runtime_input.get("cc")) + _as_list(runtime_input.get("bcc"))
    username = str(secrets.get("username") or "")
    password = str(secrets.get("password") or "")
    use_tls = _as_bool(connection.get("use_tls"), default=True)
    starttls = _as_bool(connection.get("starttls"), default=False)
    smtp_class = _DryRunSMTP if dry_run else (smtplib.SMTP_SSL if use_tls and not starttls else smtplib.SMTP)
    with smtp_class(host, port, timeout=timeout) as smtp:
        if starttls and hasattr(smtp, "starttls"):
            smtp.starttls()
        if username or password:
            smtp.login(username, password)
        refused = smtp.send_message(message)
    return {{"status": "completed", "tool_id": TOOL_ID, "data": {{"dry_run": dry_run, "host": host, "port": port, "recipient_count": len(recipients), "subject": str(message["Subject"]), "refused_recipients": refused or {{}}, "sent": not dry_run}}, "message": "Message flow completed.", "provenance": {{"source": "runtime_generated_tool", "side_effects": not dry_run}}}}
'''
        test = f'''from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[2] / "tools" / {tool_id!r}
SPEC = importlib.util.spec_from_file_location("generated_tool_under_test", ROOT / {module!r})
mod = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(mod)


def test_generated_tool_dry_run_contract():
    result = getattr(mod, {function!r})({verification_input_repr})
    assert result["status"] == "completed"
    assert result["tool_id"] == {tool_id!r}
    assert result["data"]["dry_run"] is True
    assert result["data"]["recipient_count"] == 1
'''
        return [{"path": module, "content": code}, {"path": f"test_{tool_id}.py", "content": test}]

    def _valid_files(self, files: list[Any]) -> bool:
        return bool(files) and all(isinstance(item, dict) and str(item.get("path") or "").strip() and isinstance(item.get("content"), str) for item in files)

    def _schema_or_default(self, value: Any, name: str) -> dict[str, Any]:
        if isinstance(value, dict) and value:
            props = value.get("properties") if isinstance(value.get("properties"), dict) else {}
            if name == "output" or props or value.get("additionalProperties") is not True:
                return value
        if name == "output":
            return {
                "type": "object",
                "required": ["status", "data"],
                "properties": {"status": {"type": "string"}, "data": {"type": "object"}, "message": {"type": "string"}, "provenance": {"type": "object"}},
                "additionalProperties": False,
            }
        return {
            "type": "object",
            "required": ["operation", "name"],
            "properties": {
                "operation": {"type": "string"},
                "name": {"type": "string", "minLength": 1},
                "definition": {"type": "object", "default": {}},
                "patch": {"type": "object", "default": {}},
                "enabled": {"type": "boolean"},
                "dry_run": {"type": "boolean", "default": False},
            },
            "additionalProperties": True,
        }

    def _closed_schema(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict) and value:
            schema = dict(value)
            schema.setdefault("type", "object")
            schema.setdefault("properties", {})
            schema.setdefault("required", [])
            schema.setdefault("additionalProperties", False)
            return schema
        return {"type": "object", "properties": {}, "required": [], "additionalProperties": False, "x-empty-schema-allowed": True}

    def _files_look_like_stub(self, files: list[Any]) -> bool:
        text = "\n".join(str(item.get("content") or "") for item in files if isinstance(item, dict)).casefold()
        return any(marker in text for marker in ["blueprint only", "requires_runtime_implementation", "runtime blueprint artifact verified"])

    def _allows_runtime_native_materialization(self, blueprint: dict[str, Any], identity_contract: dict[str, Any]) -> bool:
        policy = blueprint.get("acquisition_policy") if isinstance(blueprint.get("acquisition_policy"), dict) else {}
        if bool(policy.get("allow_policy_backed_basic_acquisition_without_external_evidence")):
            return True
        text = json.dumps({"blueprint": blueprint, "identity": identity_contract}, ensure_ascii=False).casefold()
        positive = ["standard library", "no external package", "local runtime", "runtime storage", "persist", "basic"]
        negative = ["external api", "oauth", "browser", "sdk", "install package"]
        return any(item in text for item in positive) and not any(item in text for item in negative)

    def _generic_verification_input(self, input_schema: dict[str, Any]) -> dict[str, Any]:
        return {"input": {"operation": "create", "name": "sandbox_check", "definition": {"value": "dry_run"}, "enabled": True, "dry_run": True}, "connection": {}, "secrets": {}, "_runtime": {"dry_run": True}}

    def _generic_stateful_files(self, *, tool_id: str, entrypoint: dict[str, Any], input_schema: dict[str, Any]) -> list[dict[str, str]]:
        module = str(entrypoint.get("module") or "tool.py")
        function = str(entrypoint.get("function") or "run")
        verification_input_repr = repr(self._generic_verification_input(input_schema))
        code = f'''from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TOOL_ID = {tool_id!r}


def _as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {{}}


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().casefold()
    if text in {{"true", "1", "yes", "y", "on"}}:
        return True
    if text in {{"false", "0", "no", "n", "off"}}:
        return False
    return default


def _store_path(runtime: dict[str, Any]) -> Path:
    root = runtime.get("storage_root") or os.environ.get("AI_RUNTIME_DATA_DIR") or "runtime/data"
    path = Path(str(root)) / "runtime_capabilities" / TOOL_ID / "records.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = {{}}
    return data if isinstance(data, dict) else {{}}


def _save(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _normalize_operation(value: Any) -> str:
    text = str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
    aliases = {{"add": "create", "set": "create", "remove": "delete", "start": "enable", "stop": "disable"}}
    return aliases.get(text, text or "list")


def {function}(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = _as_mapping(payload)
    runtime = _as_mapping(payload.get("_runtime"))
    runtime_input = _as_mapping(payload.get("input") or payload.get("runtime_input") or payload.get("parameters") or payload)
    operation = _normalize_operation(runtime_input.get("operation"))
    name = str(runtime_input.get("name") or runtime_input.get("id") or runtime_input.get("resource_name") or "").strip()
    dry_run = _as_bool(runtime_input.get("dry_run", runtime.get("dry_run")), default=False)
    path = _store_path(runtime)
    records = _load(path)
    now = datetime.now(timezone.utc).isoformat()

    if operation in {{"create", "update", "upsert"}}:
        if not name:
            raise ValueError("input.name is required")
        current = records.get(name) if isinstance(records.get(name), dict) else {{}}
        definition = _as_mapping(runtime_input.get("definition"))
        patch = _as_mapping(runtime_input.get("patch"))
        merged = {{**current, **definition, **patch}}
        if "enabled" in runtime_input:
            merged["enabled"] = _as_bool(runtime_input.get("enabled"), default=bool(current.get("enabled", True)))
        else:
            merged.setdefault("enabled", True)
        merged["name"] = name
        merged["updated_at"] = now
        merged.setdefault("created_at", current.get("created_at") or now)
        records[name] = merged
        if not dry_run:
            _save(path, records)
        data = {{"name": name, "record": merged, "dry_run": dry_run}}
    elif operation in {{"delete"}}:
        if not name:
            raise ValueError("input.name is required")
        existed = name in records
        if existed and not dry_run:
            records.pop(name, None)
            _save(path, records)
        data = {{"name": name, "deleted": existed, "dry_run": dry_run}}
    elif operation in {{"enable", "disable"}}:
        if not name:
            raise ValueError("input.name is required")
        current = records.get(name) if isinstance(records.get(name), dict) else {{"name": name}}
        current["enabled"] = operation == "enable"
        current["updated_at"] = now
        records[name] = current
        if not dry_run:
            _save(path, records)
        data = {{"name": name, "enabled": current["enabled"], "dry_run": dry_run}}
    elif operation in {{"read", "get"}}:
        if not name:
            raise ValueError("input.name is required")
        data = {{"name": name, "record": records.get(name), "found": name in records}}
    else:
        items = list(records.values())
        data = {{"records": items, "count": len(items)}}

    return {{"status": "completed", "tool_id": TOOL_ID, "data": data, "message": "Runtime-native operation completed.", "provenance": {{"source": "runtime_native_generated_tool", "storage_path": str(path)}}}}
'''
        test = f'''from pathlib import Path
import importlib.util
import tempfile

ROOT = Path(__file__).resolve().parents[2] / "tools" / {tool_id!r}
SPEC = importlib.util.spec_from_file_location("generated_tool_under_test", ROOT / {module!r})
mod = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(mod)


def test_generated_tool_persists_named_record():
    with tempfile.TemporaryDirectory() as tmp:
        result = getattr(mod, {function!r})({{"input": {{"operation": "create", "name": "sandbox_check", "definition": {{"value": "ok"}}, "enabled": True}}, "connection": {{}}, "secrets": {{}}, "_runtime": {{"storage_root": tmp}}}})
        assert result["status"] == "completed"
        listed = getattr(mod, {function!r})({{"input": {{"operation": "list"}}, "_runtime": {{"storage_root": tmp}}}})
        assert listed["data"]["count"] == 1


def test_generated_tool_enable_disable_delete():
    with tempfile.TemporaryDirectory() as tmp:
        getattr(mod, {function!r})({{"input": {{"operation": "create", "name": "x", "definition": {{}}}}, "_runtime": {{"storage_root": tmp}}}})
        disabled = getattr(mod, {function!r})({{"input": {{"operation": "disable", "name": "x"}}, "_runtime": {{"storage_root": tmp}}}})
        assert disabled["data"]["enabled"] is False
        enabled = getattr(mod, {function!r})({{"input": {{"operation": "enable", "name": "x"}}, "_runtime": {{"storage_root": tmp}}}})
        assert enabled["data"]["enabled"] is True
        deleted = getattr(mod, {function!r})({{"input": {{"operation": "delete", "name": "x"}}, "_runtime": {{"storage_root": tmp}}}})
        assert deleted["data"]["deleted"] is True


def test_generated_tool_verification_input():
    result = getattr(mod, {function!r})({verification_input_repr})
    assert result["status"] == "completed"
'''
        return [{"path": module, "content": code}, {"path": f"test_{tool_id}.py", "content": test}]

    def _neutral_files(self, *, tool_id: str, entrypoint: dict[str, Any]) -> list[dict[str, str]]:
        module = str(entrypoint.get("module") or "tool.py")
        function = str(entrypoint.get("function") or "run")
        code = f'''from __future__ import annotations
from typing import Any
TOOL_ID = {tool_id!r}
def {function}(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {{"status": "blueprint_generated", "tool_id": TOOL_ID, "data": {{}}, "message": "Blueprint only; not a registerable runtime implementation."}}
'''
        test = f'''from pathlib import Path
import importlib.util
ROOT = Path(__file__).resolve().parents[2] / "tools" / {tool_id!r}
SPEC = importlib.util.spec_from_file_location("generated_tool_under_test", ROOT / {module!r})
mod = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(mod)
def test_blueprint_only_contract():
    result = getattr(mod, {function!r})({{"_runtime": {{"dry_run": True}}}})
    assert result["status"] == "blueprint_generated"
'''
        return [{"path": module, "content": code}, {"path": f"test_{tool_id}.py", "content": test}]

    def _safe_name(self, value: str) -> str:
        return "".join(c if c.isalnum() else "_" for c in str(value)).strip("_").lower() or "generated_capability"
