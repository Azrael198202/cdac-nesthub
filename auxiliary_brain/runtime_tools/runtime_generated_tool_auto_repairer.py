from __future__ import annotations

import json
import os
import py_compile
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_GENERATED, RUNTIME_TRACES


class RuntimeGeneratedToolAutoRepairer:
    """Capability-neutral repair loop for generated runtime tool failures.

    The repairer never branches on a concrete capability id or business word.
    It uses only the registered runtime contracts, the failing input, the error
    envelope, and generic operation semantics. When it can safely patch a
    generated Python artifact, it backs up the old file, writes a patched module,
    compiles it, records a trace, and lets the caller retry the original request.
    """

    def __init__(self, *, trace_root: Path | None = None) -> None:
        self.trace_root = trace_root or (RUNTIME_TRACES / "runtime_execution_repair")

    def attempt_repair(
        self,
        *,
        run_id: str,
        tool_id: str,
        tool_spec: dict[str, Any],
        invocation_payload: dict[str, Any],
        failure_result: dict[str, Any],
    ) -> dict[str, Any]:
        self._record(run_id, "repair_started", "running", {
            "tool_id": tool_id,
            "error": self._error_summary(failure_result),
        })
        implementation = tool_spec.get("implementation") if isinstance(tool_spec.get("implementation"), dict) else {}
        module_path = implementation.get("module_path") or implementation.get("path")
        if not module_path:
            result = {"status": "not_repairable", "reason": "missing_module_path"}
            self._record(run_id, "repair_finished", "not_repairable", result)
            return result
        path = Path(str(module_path))
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists():
            result = {"status": "not_repairable", "reason": "module_path_not_found", "module_path": str(path)}
            self._record(run_id, "repair_finished", "not_repairable", result)
            return result

        input_schema = tool_spec.get("input_schema") if isinstance(tool_spec.get("input_schema"), dict) else {}
        connection_schema = tool_spec.get("connection_schema") if isinstance(tool_spec.get("connection_schema"), dict) else {}
        output_schema = tool_spec.get("output_schema") if isinstance(tool_spec.get("output_schema"), dict) else {}
        operation_values = self._operation_values(input_schema)
        if not operation_values:
            result = {"status": "not_repairable", "reason": "no_operation_contract"}
            self._record(run_id, "repair_finished", "not_repairable", result)
            return result

        generated = self._build_contract_driven_module(
            tool_id=tool_id,
            operation_values=operation_values,
            input_schema=input_schema,
            connection_schema=connection_schema,
            output_schema=output_schema,
        )
        backup_path = path.with_suffix(path.suffix + f".bak_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}")
        try:
            shutil.copy2(path, backup_path)
            path.write_text(generated, encoding="utf-8")
            py_compile.compile(str(path), doraise=True)
        except Exception as exc:
            try:
                if backup_path.exists():
                    shutil.copy2(backup_path, path)
            except Exception:
                pass
            result = {"status": "repair_patch_failed", "reason": str(exc), "module_path": str(path), "backup_path": str(backup_path)}
            self._record(run_id, "repair_finished", "failed", result)
            return result

        result = {
            "status": "repair_patch_applied",
            "module_path": str(path),
            "backup_path": str(backup_path),
            "validation": {"py_compile": "passed"},
            "repair_contract": "generic_operation_dispatcher",
        }
        self._record(run_id, "repair_finished", "patched", result)
        return result

    def _operation_values(self, input_schema: dict[str, Any]) -> list[str]:
        props = input_schema.get("properties") if isinstance(input_schema.get("properties"), dict) else {}
        op = props.get("operation") if isinstance(props.get("operation"), dict) else {}
        values = op.get("enum") if isinstance(op.get("enum"), list) else []
        return [str(v) for v in values if str(v).strip()]

    def _build_contract_driven_module(self, *, tool_id: str, operation_values: list[str], input_schema: dict[str, Any], connection_schema: dict[str, Any], output_schema: dict[str, Any]) -> str:
        contract = {
            "tool_id": tool_id,
            "operations": operation_values,
            "input_schema": input_schema,
            "connection_schema": connection_schema,
            "output_schema": output_schema,
        }
        return f'''from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CONTRACT = {repr(contract)}


def run(payload: dict[str, Any]) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    try:
        envelope = payload if isinstance(payload, dict) else {{}}
        input_data = envelope.get("input") if isinstance(envelope.get("input"), dict) else envelope
        connection = envelope.get("connection") if isinstance(envelope.get("connection"), dict) else {{}}
        operation = str(input_data.get("operation") or "").strip()
        if not operation:
            return _out(operation, False, None, None, "operation is required", 0, started)
        store = _Store(connection=connection, input_schema=CONTRACT.get("input_schema") or {{}}, connection_schema=CONTRACT.get("connection_schema") or {{}})
        return store.dispatch(operation=operation, input_data=input_data, started=started)
    except Exception as exc:
        return _out("", False, None, None, str(exc), 0, started)


class _Store:
    def __init__(self, *, connection: dict[str, Any], input_schema: dict[str, Any], connection_schema: dict[str, Any]) -> None:
        self.input_schema = input_schema if isinstance(input_schema, dict) else {{}}
        self.connection_schema = connection_schema if isinstance(connection_schema, dict) else {{}}
        self.connection = self._connection_with_defaults(connection if isinstance(connection, dict) else {{}})
        self.db_path = self._database_path()
        self.table_name = self._table_name()
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_table()

    def dispatch(self, *, operation: str, input_data: dict[str, Any], started: datetime) -> dict[str, Any]:
        verb = _operation_verb(operation)
        if verb == "create":
            return self.create(operation, input_data, started)
        if verb == "get":
            return self.get(operation, input_data, started)
        if verb == "list":
            return self.list(operation, input_data, started)
        if verb == "search":
            return self.search(operation, input_data, started)
        if verb == "update":
            return self.update(operation, input_data, started)
        if verb == "delete":
            return self.delete(operation, input_data, started)
        return _out(operation, False, None, None, "unsupported operation", 0, started)

    def create(self, operation: str, input_data: dict[str, Any], started: datetime) -> dict[str, Any]:
        record_key = self._record_object_key()
        record = input_data.get(record_key) if record_key and isinstance(input_data.get(record_key), dict) else {{}}
        if not isinstance(record, dict):
            record = {{}}
        record_id_key = self._record_id_key(record)
        record_id = str(record.get(record_id_key) or input_data.get(record_id_key) or uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        record = dict(record)
        record.setdefault(record_id_key, record_id)
        record.setdefault("created_at", now)
        record["updated_at"] = now
        self._upsert_record(record_id=record_id, record=record)
        return _out(operation, True, record_id, record, None, 1, started)

    def get(self, operation: str, input_data: dict[str, Any], started: datetime) -> dict[str, Any]:
        record_id = self._input_record_id(input_data)
        if not record_id:
            return _out(operation, False, None, None, "record id is required", 0, started)
        record = self._load_record(record_id)
        return _out(operation, record is not None, record_id, record, None if record is not None else "record not found", 1 if record is not None else 0, started)

    def list(self, operation: str, input_data: dict[str, Any], started: datetime) -> dict[str, Any]:
        filters = input_data.get("filters") if isinstance(input_data.get("filters"), dict) else {{}}
        limit = _safe_int(input_data.get("limit"), 50)
        offset = _safe_int(input_data.get("offset"), 0)
        records = self._all_records()
        records = [r for r in records if self._matches_filters(r, filters)]
        records.sort(key=lambda r: str(r.get("start_time") or r.get("created_at") or r.get("updated_at") or ""))
        return _out(operation, True, None, records[offset: offset + limit], None, len(records[offset: offset + limit]), started)

    def search(self, operation: str, input_data: dict[str, Any], started: datetime) -> dict[str, Any]:
        query = str(input_data.get("query") or "").casefold()
        filters = input_data.get("filters") if isinstance(input_data.get("filters"), dict) else {{}}
        limit = _safe_int(input_data.get("limit"), 50)
        offset = _safe_int(input_data.get("offset"), 0)
        records = [r for r in self._all_records() if self._matches_filters(r, filters)]
        if query:
            records = [r for r in records if query in json.dumps(r, ensure_ascii=False, default=str).casefold()]
        records.sort(key=lambda r: str(r.get("start_time") or r.get("created_at") or r.get("updated_at") or ""))
        return _out(operation, True, None, records[offset: offset + limit], None, len(records[offset: offset + limit]), started)

    def update(self, operation: str, input_data: dict[str, Any], started: datetime) -> dict[str, Any]:
        record_id = self._input_record_id(input_data)
        updates = input_data.get("update_fields") if isinstance(input_data.get("update_fields"), dict) else {{}}
        if not record_id:
            return _out(operation, False, None, None, "record id is required", 0, started)
        current = self._load_record(record_id)
        if current is None:
            return _out(operation, False, record_id, None, "record not found", 0, started)
        current.update(updates)
        current["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._upsert_record(record_id=record_id, record=current)
        return _out(operation, True, record_id, current, None, 1, started)

    def delete(self, operation: str, input_data: dict[str, Any], started: datetime) -> dict[str, Any]:
        record_id = self._input_record_id(input_data)
        if not record_id:
            return _out(operation, False, None, None, "record id is required", 0, started)
        current = self._load_record(record_id)
        if current is None:
            return _out(operation, False, record_id, None, "record not found", 0, started)
        meta = current.get("metadata") if isinstance(current.get("metadata"), dict) else {{}}
        input_meta = input_data.get("metadata") if isinstance(input_data.get("metadata"), dict) else {{}}
        force = bool(meta.get("force_delete") or input_meta.get("force_delete"))
        if force:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(f'DELETE FROM "{{self.table_name}}" WHERE record_id=?', (record_id,))
                conn.commit()
            return _out(operation, True, record_id, {{"deleted": True}}, None, 1, started)
        current["status"] = "cancelled"
        current["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._upsert_record(record_id=record_id, record=current)
        return _out(operation, True, record_id, current, None, 1, started)

    def _connection_with_defaults(self, values: dict[str, Any]) -> dict[str, Any]:
        out = {{}}
        props = self.connection_schema.get("properties") if isinstance(self.connection_schema.get("properties"), dict) else {{}}
        for key, spec in props.items():
            if isinstance(spec, dict) and "default" in spec:
                out[str(key)] = spec.get("default")
        out.update({{k: v for k, v in values.items() if v not in {{None, ""}}}})
        return out

    def _database_path(self) -> str:
        for key, value in self.connection.items():
            key_text = str(key).casefold()
            if "path" in key_text or "database" in key_text or "db" == key_text:
                return str(value)
        return "runtime/memory/runtime_store.db"

    def _table_name(self) -> str:
        for key, value in self.connection.items():
            key_text = str(key).casefold()
            if "table" in key_text and str(value).strip():
                return _safe_identifier(str(value))
        return _safe_identifier(str(CONTRACT.get("tool_id") or "records"))

    def _init_table(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(f'CREATE TABLE IF NOT EXISTS "{{self.table_name}}" (record_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, created_at TEXT, updated_at TEXT)')
            conn.commit()

    def _record_object_key(self) -> str:
        props = self.input_schema.get("properties") if isinstance(self.input_schema.get("properties"), dict) else {{}}
        for key, spec in props.items():
            if key in {{"filters", "update_fields"}}:
                continue
            if isinstance(spec, dict) and spec.get("type") == "object" and key != "metadata":
                return str(key)
        return ""

    def _record_id_key(self, record: dict[str, Any]) -> str:
        for key in record.keys():
            text = str(key).casefold()
            if text == "id" or text.endswith("_id"):
                return str(key)
        props = self.input_schema.get("properties") if isinstance(self.input_schema.get("properties"), dict) else {{}}
        for key in props.keys():
            text = str(key).casefold()
            if text == "id" or text.endswith("_id"):
                return str(key)
        return "record_id"

    def _input_record_id(self, input_data: dict[str, Any]) -> str:
        for key, value in input_data.items():
            text = str(key).casefold()
            if (text == "id" or text.endswith("_id")) and value not in {{None, ""}}:
                return str(value)
        return ""

    def _upsert_record(self, *, record_id: str, record: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        created = str(record.get("created_at") or now)
        updated = str(record.get("updated_at") or now)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(f'INSERT OR REPLACE INTO "{{self.table_name}}" (record_id, payload_json, created_at, updated_at) VALUES (?, ?, ?, ?)', (record_id, json.dumps(record, ensure_ascii=False, default=str), created, updated))
            conn.commit()

    def _load_record(self, record_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(f'SELECT payload_json FROM "{{self.table_name}}" WHERE record_id=?', (record_id,)).fetchone()
        if not row:
            return None
        try:
            data = json.loads(row[0])
            return data if isinstance(data, dict) else {{"value": data}}
        except Exception:
            return {{"value": row[0]}}

    def _all_records(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(f'SELECT payload_json FROM "{{self.table_name}}"').fetchall()
        out = []
        for row in rows:
            try:
                data = json.loads(row[0])
                out.append(data if isinstance(data, dict) else {{"value": data}})
            except Exception:
                out.append({{"value": row[0]}})
        return out

    def _matches_filters(self, record: dict[str, Any], filters: dict[str, Any]) -> bool:
        for key, value in filters.items():
            if value in {{None, "", []}}:
                continue
            rv = record.get(key)
            if isinstance(rv, list):
                if value not in rv and str(value) not in [str(x) for x in rv]:
                    return False
            elif isinstance(value, list):
                if rv not in value and str(rv) not in [str(x) for x in value]:
                    return False
            else:
                if str(rv) != str(value):
                    return False
        return True


def _operation_verb(operation: str) -> str:
    text = str(operation or "").casefold()
    if any(t in text for t in ["create", "add", "insert", "register"]):
        return "create"
    if any(t in text for t in ["get", "read", "fetch"]):
        return "get"
    if any(t in text for t in ["list", "all"]):
        return "list"
    if any(t in text for t in ["search", "find", "query"]):
        return "search"
    if any(t in text for t in ["update", "modify", "change", "edit"]):
        return "update"
    if any(t in text for t in ["delete", "remove", "cancel"]):
        return "delete"
    return ""


def _safe_identifier(value: str) -> str:
    out = "".join(c if c.isalnum() or c == "_" else "_" for c in str(value or "records"))
    return out.strip("_") or "records"


def _safe_int(value: Any, default: int) -> int:
    try:
        return max(0, int(value))
    except Exception:
        return default


def _out(operation: str, success: bool, record_id: str | None, result: Any, error: Any, affected_count: int, started: datetime) -> dict[str, Any]:
    return {{
        "status": "success" if success else "failed",
        "operation": operation,
        "success": bool(success),
        **_id_outputs(record_id),
        "record_id": record_id,
        "result": result,
        "error": error,
        "affected_count": int(affected_count or 0),
        "execution_time_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_ms": int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
    }}


def _id_outputs(record_id: str | None) -> dict[str, Any]:
    out = {{}}
    output_schema = CONTRACT.get("output_schema") if isinstance(CONTRACT.get("output_schema"), dict) else {{}}
    props = output_schema.get("properties") if isinstance(output_schema.get("properties"), dict) else {{}}
    for key in props.keys():
        text = str(key).casefold()
        if text == "id" or text.endswith("_id"):
            out[str(key)] = record_id
    return out
'''

    def _record(self, run_id: str, stage: str, status: str, payload: dict[str, Any]) -> None:
        safe_run = self._safe_name(run_id or "runtime_execution_repair")
        path = self.trace_root / f"{safe_run}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "at": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "stage": stage,
            "status": status,
            "payload": self._json_safe(payload),
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")

    def _error_summary(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {"message": str(value)[:1000]}
        err = value.get("error") if isinstance(value.get("error"), dict) else {}
        return {
            "status": value.get("status"),
            "code": err.get("code"),
            "message": str(err.get("message") or value.get("message") or value)[:1000],
        }

    def _json_safe(self, value: Any) -> Any:
        try:
            json.dumps(value, ensure_ascii=False, default=str)
            return value
        except Exception:
            return json.loads(json.dumps(value, ensure_ascii=False, default=str))

    def _safe_name(self, value: str) -> str:
        return "".join(c if c.isalnum() or c in {"_", "-"} else "_" for c in str(value)).strip("_") or "unknown"
