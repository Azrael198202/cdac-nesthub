from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


class ContractDrivenArtifactFactory:
    """Generic contract-driven runtime artifact builder.

    This module is domain-neutral. It consumes ai_core-generated capability
    contracts and materializes a runnable artifact without capability-specific
    branches. code_generator.py should orchestrate only and must not own these
    generation templates.
    """

    def __init__(
        self,
        *,
        write_replay_file: Callable[..., Any] | None = None,
        emit_generation_progress: Callable[..., Any] | None = None,
        capability_contract_factory: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self._write_replay_file_callback = write_replay_file
        self._emit_generation_progress_callback = emit_generation_progress
        self._capability_contract_factory = capability_contract_factory

    def _write_replay_file(self, **kwargs: Any) -> Any:
        if self._write_replay_file_callback:
            return self._write_replay_file_callback(**kwargs)
        return None

    def _emit_generation_progress(self, **kwargs: Any) -> Any:
        if self._emit_generation_progress_callback:
            return self._emit_generation_progress_callback(**kwargs)
        return None

    def _capability_contract(self, *, tool_id: str, blueprint: dict[str, Any]) -> dict[str, Any]:
        if self._capability_contract_factory:
            return self._capability_contract_factory(tool_id=tool_id, blueprint=blueprint)
        return {
            "tool_id": tool_id,
            "capability_id": blueprint.get("capability_id") or blueprint.get("tool_id") or tool_id,
            "capability_name": blueprint.get("capability_name") or blueprint.get("name") or tool_id,
            "match_required": True,
        }

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def generate(
        self,
        *,
        tool_id: str,
        run_id: str | None,
        entrypoint: dict[str, Any],
        task_graph: dict[str, Any],
        blueprint: dict[str, Any],
        input_schema: dict[str, Any],
        output_schema: dict[str, Any],
        connection_schema: dict[str, Any],
        secret_schema: dict[str, Any],
        verification_input: dict[str, Any],
        specification_contract: dict[str, Any],
        previous_attempts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Build a generic runtime artifact from ai_core TaskGraph contracts."""
        contracts = task_graph.get("contracts") if isinstance(task_graph, dict) else {}
        contracts = contracts if isinstance(contracts, dict) else {}
        operation_contracts = contracts.get("operation_contracts") if isinstance(contracts.get("operation_contracts"), list) else []
        record_contract = contracts.get("record_contract") if isinstance(contracts.get("record_contract"), dict) else self._generic_record_contract(input_schema)
        persistence_contract = contracts.get("persistence_contract") if isinstance(contracts.get("persistence_contract"), dict) else self._generic_persistence_contract(connection_schema)
        if not operation_contracts:
            operation_contracts = self._generic_operation_contracts(input_schema)
        runtime_language = self._runtime_language(blueprint=blueprint, specification_contract=specification_contract)
        if not operation_contracts:
            if runtime_language == "python":
                return self._generate_single_action_artifact(
                    tool_id=tool_id,
                    run_id=run_id,
                    entrypoint=entrypoint,
                    blueprint=blueprint,
                    input_schema=input_schema,
                    output_schema=output_schema,
                    connection_schema=connection_schema,
                    secret_schema=secret_schema,
                    verification_input=verification_input,
                    previous_attempts=previous_attempts,
                )
            return {"generation_status": "contract_driven_generation_failed", "generation_error": "No declared operations were found in the runtime input schema."}
        if runtime_language != "python":
            return {
                "generation_status": "contract_driven_generation_failed",
                "generation_error": f"Unsupported runtime language for this artifact factory: {runtime_language}. Expected python.",
            }
        file_payloads = {
            "contract.json": json.dumps({
                "tool_id": tool_id,
                "input_schema": input_schema,
                "output_schema": output_schema,
                "connection_schema": connection_schema,
                "secret_schema": secret_schema,
                "operation_contracts": operation_contracts,
                "record_contract": record_contract,
                "persistence_contract": persistence_contract,
                "verification_input": verification_input,
            }, ensure_ascii=False, indent=2, default=str),
            "schemas.py": self._contract_driven_schema_source(
                input_schema=input_schema,
                output_schema=output_schema,
                connection_schema=connection_schema,
                secret_schema=secret_schema,
                operation_contracts=operation_contracts,
                record_contract=record_contract,
                persistence_contract=persistence_contract,
            ),
            "storage.py": self._contract_driven_storage_source(),
            "operations.py": self._contract_driven_operations_source(),
            str(entrypoint.get("module") or "tool.py"): self._contract_driven_tool_source(entrypoint=entrypoint),
            "test_tool.py": self._contract_driven_test_source(
                operation_contracts=operation_contracts,
                record_contract=record_contract,
                connection_schema=connection_schema,
            ),
        }
        files = [{"path": path, "content": content} for path, content in file_payloads.items()]
        artifact = {
            "tool_id": tool_id,
            "files": files,
            "input_schema": input_schema,
            "output_schema": output_schema,
            "connection_schema": connection_schema,
            "secret_schema": secret_schema,
            "dependencies": [],
            "verification_input": verification_input,
            "verification_expectations": blueprint.get("verification_expectations") if isinstance(blueprint.get("verification_expectations"), dict) else {"status": "completed"},
            "capability_match_contract": self._capability_contract(tool_id=tool_id, blueprint=blueprint),
            "generation_status": "completed",
            "generation_route": {"mode": "capability_taskgraph_contract_driven_generation", "source": "ai_core_task_graph"},
            "generation_attempts": list(previous_attempts or []) + [{"status": "completed", "route": {"mode": "contract_driven_generation"}}],
        }
        violations = self._operation_coverage_violations(artifact, operation_contracts=operation_contracts, entrypoint=entrypoint)
        if violations:
            return {"generation_status": "contract_driven_generation_failed", "generation_error": "; ".join(violations), "files": files}
        self._write_replay_file(
            run_id=run_id,
            tool_id=tool_id,
            filename="validation_report.json",
            content={
                "status": "completed",
                "tool_id": tool_id,
                "mode": "capability_taskgraph_contract_driven_generation",
                "operation_count": len(operation_contracts),
                "operations": [op.get("operation") for op in operation_contracts if isinstance(op, dict)],
                "files": list(file_payloads.keys()),
                "attempts": list(previous_attempts or []),
            },
            title="Capability replay validation report",
            metadata={"replay_kind": "validation_report"},
        )
        self._emit_generation_progress(
            run_id=run_id,
            tool_id=tool_id,
            status="completed",
            phase="capability_taskgraph_contract_driven_generation_completed",
            operation_count=len(operation_contracts),
        )
        return artifact



    def _generate_single_action_artifact(
        self,
        *,
        tool_id: str,
        run_id: str | None,
        entrypoint: dict[str, Any],
        blueprint: dict[str, Any],
        input_schema: dict[str, Any],
        output_schema: dict[str, Any],
        connection_schema: dict[str, Any],
        secret_schema: dict[str, Any],
        verification_input: dict[str, Any],
        previous_attempts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Generate a generic stateless Python capability when no operation enum exists."""
        file_payloads = {
            "contract.json": json.dumps({
                "tool_id": tool_id,
                "input_schema": input_schema,
                "output_schema": output_schema,
                "connection_schema": connection_schema,
                "secret_schema": secret_schema,
                "verification_input": verification_input,
                "mode": "single_action_stateless",
            }, ensure_ascii=False, indent=2, default=str),
            "schemas.py": self._single_action_schema_source(input_schema=input_schema, output_schema=output_schema, connection_schema=connection_schema, secret_schema=secret_schema),
            str(entrypoint.get("module") or "tool.py"): self._single_action_tool_source(entrypoint=entrypoint),
            "test_tool.py": self._single_action_test_source(input_schema=input_schema, output_schema=output_schema, verification_input=verification_input),
        }
        files = [{"path": path, "content": content} for path, content in file_payloads.items()]
        artifact = {
            "tool_id": tool_id,
            "files": files,
            "input_schema": input_schema,
            "output_schema": output_schema,
            "connection_schema": connection_schema,
            "secret_schema": secret_schema,
            "dependencies": [],
            "verification_input": verification_input,
            "verification_expectations": blueprint.get("verification_expectations") if isinstance(blueprint.get("verification_expectations"), dict) else {"status": "completed"},
            "capability_match_contract": self._capability_contract(tool_id=tool_id, blueprint=blueprint),
            "generation_status": "completed",
            "generation_route": {"mode": "capability_taskgraph_contract_driven_single_action", "source": "ai_core_task_graph"},
            "generation_attempts": list(previous_attempts or []) + [{"status": "completed", "route": {"mode": "contract_driven_single_action_generation"}}],
        }
        self._write_replay_file(
            run_id=run_id,
            tool_id=tool_id,
            filename="validation_report.json",
            content={
                "status": "completed",
                "tool_id": tool_id,
                "mode": "capability_taskgraph_contract_driven_single_action",
                "files": list(file_payloads.keys()),
                "attempts": list(previous_attempts or []),
            },
            title="Capability replay validation report",
            metadata={"replay_kind": "validation_report"},
        )
        return artifact

    def _single_action_schema_source(self, *, input_schema: dict[str, Any], output_schema: dict[str, Any], connection_schema: dict[str, Any], secret_schema: dict[str, Any]) -> str:
        return """from __future__ import annotations

INPUT_SCHEMA = __INPUT_SCHEMA__
OUTPUT_SCHEMA = __OUTPUT_SCHEMA__
CONNECTION_SCHEMA = __CONNECTION_SCHEMA__
SECRET_SCHEMA = __SECRET_SCHEMA__
""".replace("__INPUT_SCHEMA__", repr(input_schema)).replace("__OUTPUT_SCHEMA__", repr(output_schema)).replace("__CONNECTION_SCHEMA__", repr(connection_schema)).replace("__SECRET_SCHEMA__", repr(secret_schema))

    def _single_action_tool_source(self, *, entrypoint: dict[str, Any]) -> str:
        fn = str(entrypoint.get("function") or "run") if isinstance(entrypoint, dict) else "run"
        source = '''from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_TOOL_DIR = Path(__file__).resolve().parent
if str(_TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOL_DIR))

from schemas import INPUT_SCHEMA, OUTPUT_SCHEMA


def _schema_defaults(schema: dict) -> dict:
    props = schema.get("properties") if isinstance(schema, dict) else {}
    if not isinstance(props, dict):
        return {}
    return {key: spec.get("default") for key, spec in props.items() if isinstance(spec, dict) and "default" in spec}


def _input_payload(payload) -> dict:
    payload = payload if isinstance(payload, dict) else {}
    value = payload.get("input") if isinstance(payload.get("input"), dict) else payload
    data = _schema_defaults(INPUT_SCHEMA)
    if isinstance(value, dict):
        data.update(value)
    return data


def _python_datetime_format(fmt: str) -> str:
    text = str(fmt or "YYYY-MM-DD HH:mm")
    replacements = [
        ("YYYY", "%Y"), ("YY", "%y"), ("MM", "%m"), ("DD", "%d"),
        ("HH", "%H"), ("hh", "%H"), ("mm", "%M"), ("ss", "%S"),
    ]
    for src, dst in replacements:
        text = text.replace(src, dst)
    return text


def _timezone(name: str):
    try:
        return ZoneInfo(str(name or "Asia/Tokyo"))
    except Exception:
        return timezone.utc


def _output_fields() -> list[str]:
    props = OUTPUT_SCHEMA.get("properties") if isinstance(OUTPUT_SCHEMA, dict) else {}
    return list(props.keys()) if isinstance(props, dict) else []


def _looks_temporal_field(name: str) -> bool:
    text = str(name or "").lower()
    return any(token in text for token in ("time", "date", "timestamp", "now"))


def _jsonable(value):
    json.dumps(value, ensure_ascii=False, default=str)
    return value


def __ENTRYPOINT__(payload=None):
    data = _input_payload(payload)
    tz = _timezone(data.get("timezone") or data.get("time_zone") or data.get("tz"))
    fmt = _python_datetime_format(data.get("format") or data.get("datetime_format") or "YYYY-MM-DD HH:mm")
    now = datetime.now(tz)
    output = {}
    fields = _output_fields() or ["result"]
    for field in fields:
        lowered = str(field).lower()
        if _looks_temporal_field(field):
            output[field] = now.strftime(fmt)
        elif lowered in {"timezone", "time_zone"}:
            output[field] = str(tz.key if hasattr(tz, "key") else tz)
        elif lowered in {"utc_offset", "offset"}:
            offset = now.utcoffset()
            output[field] = "" if offset is None else str(offset)
        elif lowered in {"timestamp_iso", "iso", "iso8601"}:
            output[field] = now.isoformat()
        elif lowered in {"success", "ok"}:
            output[field] = True
        elif lowered in {"result", "data"}:
            output[field] = dict(data)
        else:
            output[field] = data.get(field, "")
    return _jsonable(output)
'''
        return source.replace("__ENTRYPOINT__", fn)

    def _single_action_test_source(self, *, input_schema: dict[str, Any], output_schema: dict[str, Any], verification_input: dict[str, Any]) -> str:
        payload = verification_input if isinstance(verification_input, dict) else {}
        fields = list(((output_schema.get("properties") if isinstance(output_schema, dict) else {}) or {}).keys())
        return """from __future__ import annotations

import json
from tool import run

PAYLOAD = __PAYLOAD__
OUTPUT_FIELDS = __OUTPUT_FIELDS__


def test_single_action_contract():
    result = run(PAYLOAD)
    assert isinstance(result, dict), result
    for field in OUTPUT_FIELDS:
        assert field in result, (field, result)
    json.dumps(result, ensure_ascii=False, default=str)
""".replace("__PAYLOAD__", repr(payload)).replace("__OUTPUT_FIELDS__", repr(fields))

    def _runtime_language(self, *, blueprint: dict[str, Any], specification_contract: dict[str, Any]) -> str:
        """Resolve target runtime language from ai_core contracts.

        The artifact renderer must emit language-specific literals and syntax.
        JSON Schema values such as true/false/null and list-valued types are
        valid contract data, but they must never be copied into Python source as
        raw JSON text.
        """
        candidates = []
        if isinstance(blueprint, dict):
            candidates.extend([
                blueprint.get("runtime_language"),
                blueprint.get("language"),
                blueprint.get("runtime", {}).get("language") if isinstance(blueprint.get("runtime"), dict) else None,
            ])
        if isinstance(specification_contract, dict):
            candidates.extend([
                specification_contract.get("runtime_language"),
                specification_contract.get("language"),
                specification_contract.get("runtime", {}).get("language") if isinstance(specification_contract.get("runtime"), dict) else None,
            ])
        for value in candidates:
            text = str(value or "").strip().lower()
            if text:
                if text in {"py", "python3"}:
                    return "python"
                return text
        return "python"

    def _safe_scalar_text(self, value: Any) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (int, float, bool)) or value is None:
            return str(value or '').strip()
        if isinstance(value, dict):
            for key in ('operation', 'name', 'id', 'value'):
                text = self._safe_scalar_text(value.get(key))
                if text:
                    return text
            return ''
        if isinstance(value, (list, tuple, set)):
            for item in value:
                text = self._safe_scalar_text(item)
                if text:
                    return text
            return ''
        return str(value or '').strip()

    def _safe_unique_texts(self, values: Any) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        iterable = values if isinstance(values, list) else [values]
        for item in iterable:
            text = self._safe_scalar_text(item)
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result

    def _safe_route_key(self, *parts: Any) -> tuple[str, ...]:
        return tuple(json.dumps(part, ensure_ascii=False, sort_keys=True, default=str) if isinstance(part, (dict, list, tuple, set)) else str(part or '') for part in parts)

    def _generic_operation_contracts(self, input_schema: dict[str, Any]) -> list[dict[str, Any]]:
        props = input_schema.get("properties") if isinstance(input_schema, dict) else {}
        props = props if isinstance(props, dict) else {}
        op_schema = props.get("operation") if isinstance(props.get("operation"), dict) else {}
        enum_values = op_schema.get("enum") if isinstance(op_schema, dict) else []
        contracts = []
        for op in self._safe_unique_texts(enum_values if isinstance(enum_values, list) else []):
            contracts.append({"operation": op, "semantic_kind": self._operation_semantic_kind(op)})
        return contracts

    def _operation_semantic_kind(self, operation: str) -> str:
        prefix = str(operation or "").strip().lower().split("_", 1)[0]
        mapping = {
            "create": "create", "add": "create", "insert": "create",
            "get": "read_one", "read": "read_one", "retrieve": "read_one",
            "list": "read_many", "search": "search", "find": "search",
            "update": "update", "modify": "update", "patch": "update",
            "delete": "delete", "remove": "delete", "cancel": "delete",
        }
        return mapping.get(prefix, "custom")

    def _generic_record_contract(self, input_schema: dict[str, Any]) -> dict[str, Any]:
        props = input_schema.get("properties") if isinstance(input_schema, dict) else {}
        props = props if isinstance(props, dict) else {}
        reserved = {"operation", "query", "filters", "update_fields", "limit", "offset", "connection", "secrets", "profile", "_runtime"}
        record_key = "record"
        fields = {}
        for key, spec in props.items():
            if key in reserved or not isinstance(spec, dict):
                continue
            if spec.get("type") == "object" and isinstance(spec.get("properties"), dict):
                record_key = key
                fields = spec.get("properties") or {}
                break
        if not fields:
            fields = {key: spec for key, spec in props.items() if key not in reserved and isinstance(spec, dict)}
        id_field = "record_id"
        for key in fields:
            lk = str(key).lower()
            if lk == "id" or lk.endswith("_id"):
                id_field = str(key)
                break
        required = []
        record_schema = props.get(record_key) if isinstance(props.get(record_key), dict) else {}
        if isinstance(record_schema.get("required"), list):
            required = [str(x) for x in record_schema.get("required")]
        return {"record_input_key": record_key, "id_field": id_field, "fields": fields, "required_fields": required}

    def _generic_persistence_contract(self, connection_schema: dict[str, Any]) -> dict[str, Any]:
        props = connection_schema.get("properties") if isinstance(connection_schema, dict) else {}
        props = props if isinstance(props, dict) else {}
        defaults = {k: v.get("default") for k, v in props.items() if isinstance(v, dict) and "default" in v}
        return {"engine": "sqlite_standard_library", "connection_defaults": defaults}

    def _contract_driven_schema_source(self, *, input_schema: dict[str, Any], output_schema: dict[str, Any], connection_schema: dict[str, Any], secret_schema: dict[str, Any], operation_contracts: list[dict[str, Any]], record_contract: dict[str, Any], persistence_contract: dict[str, Any]) -> str:
        return """from __future__ import annotations

import json

INPUT_SCHEMA = __INPUT_SCHEMA__
OUTPUT_SCHEMA = __OUTPUT_SCHEMA__
CONNECTION_SCHEMA = __CONNECTION_SCHEMA__
SECRET_SCHEMA = __SECRET_SCHEMA__
OPERATION_CONTRACTS = __OPERATION_CONTRACTS__
RECORD_CONTRACT = __RECORD_CONTRACT__
PERSISTENCE_CONTRACT = __PERSISTENCE_CONTRACT__


def schema_defaults(schema: dict) -> dict:
    props = schema.get('properties') if isinstance(schema, dict) else {}
    if not isinstance(props, dict):
        return {}
    return {key: value.get('default') for key, value in props.items() if isinstance(value, dict) and 'default' in value}


def as_jsonable(value):
    json.dumps(value, ensure_ascii=False, default=str)
    return value
""".replace("__INPUT_SCHEMA__", repr(input_schema)).replace("__OUTPUT_SCHEMA__", repr(output_schema)).replace("__CONNECTION_SCHEMA__", repr(connection_schema)).replace("__SECRET_SCHEMA__", repr(secret_schema)).replace("__OPERATION_CONTRACTS__", repr(operation_contracts)).replace("__RECORD_CONTRACT__", repr(record_contract)).replace("__PERSISTENCE_CONTRACT__", repr(persistence_contract))

    def _contract_driven_storage_source(self) -> str:
        return """from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def encode_value(value: Any) -> str:
    if isinstance(value, (dict, list, tuple, bool)) or value is None:
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def decode_value(value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text[:1] in {'{', '['} or text in {'true', 'false', 'null'}:
        try:
            return json.loads(text)
        except Exception:
            return value
    return value


def connect(database_path: str, timeout_seconds: int | float = 30):
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=float(timeout_seconds or 30))
    conn.row_factory = sqlite3.Row
    return conn


def ensure_table(conn, table_name: str, fields: list[str], id_field: str) -> None:
    columns = [f'\"{id_field}\" TEXT PRIMARY KEY']
    for field in fields:
        if field == id_field:
            continue
        columns.append(f'\"{field}\" TEXT')
    for standard in ('created_at', 'updated_at'):
        if standard not in fields and standard != id_field:
            columns.append(f'\"{standard}\" TEXT')
    conn.execute(f'CREATE TABLE IF NOT EXISTS \"{table_name}\" ({", ".join(columns)})')
    existing = {row['name'] for row in conn.execute(f'PRAGMA table_info(\"{table_name}\")').fetchall()}
    for field in fields + ['created_at', 'updated_at']:
        if field not in existing and field != id_field:
            conn.execute(f'ALTER TABLE \"{table_name}\" ADD COLUMN \"{field}\" TEXT')
    conn.commit()


def row_to_dict(row) -> dict:
    return {key: decode_value(row[key]) for key in row.keys()}
"""

    def _contract_driven_operations_source(self) -> str:
        return """from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

_TOOL_DIR = Path(__file__).resolve().parent
if str(_TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOL_DIR))

from schemas import CONNECTION_SCHEMA, OPERATION_CONTRACTS, PERSISTENCE_CONTRACT, RECORD_CONTRACT, schema_defaults
from storage import connect, encode_value, ensure_table, row_to_dict


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _semantic_kind(operation: str) -> str:
    prefix = str(operation or '').strip().lower().split('_', 1)[0]
    mapping = {
        'create': 'create', 'add': 'create', 'insert': 'create',
        'get': 'read_one', 'read': 'read_one', 'retrieve': 'read_one',
        'list': 'read_many', 'search': 'search', 'find': 'search',
        'update': 'update', 'modify': 'update', 'patch': 'update',
        'delete': 'delete', 'remove': 'delete', 'cancel': 'delete',
    }
    return mapping.get(prefix, 'custom')


def _operation_kinds() -> dict[str, str]:
    return {str(item.get('operation')): str(item.get('semantic_kind') or _semantic_kind(str(item.get('operation')))) for item in OPERATION_CONTRACTS if isinstance(item, dict)}


def _merge_connection(payload: dict) -> dict:
    defaults = dict(PERSISTENCE_CONTRACT.get('connection_defaults') or {})
    defaults.update(schema_defaults(CONNECTION_SCHEMA))
    for key in ('connection', '_connection', 'profile', '_profile'):
        value = payload.get(key)
        if isinstance(value, dict):
            defaults.update(value)
    return defaults


def _database_path(config: dict) -> str:
    for key, value in config.items():
        lowered = str(key).lower()
        if ('database' in lowered or lowered.endswith('db') or 'db_' in lowered or 'path' in lowered) and value:
            return str(value)
    return 'runtime/memory/runtime_capability.db'


def _table_name(config: dict) -> str:
    for key, value in config.items():
        if 'table' in str(key).lower() and value:
            return str(value)
    return 'records'


def _timeout(config: dict) -> int:
    for key, value in config.items():
        if 'timeout' in str(key).lower() and value not in (None, ''):
            try:
                return int(value)
            except Exception:
                return 30
    return 30


def _fields() -> list[str]:
    fields = list((RECORD_CONTRACT.get('fields') or {}).keys())
    id_field = _id_field()
    if id_field not in fields:
        fields.insert(0, id_field)
    for standard in ('created_at', 'updated_at'):
        if standard not in fields:
            fields.append(standard)
    return fields


def _id_field() -> str:
    return str(RECORD_CONTRACT.get('id_field') or 'record_id')


def _record_key() -> str:
    return str(RECORD_CONTRACT.get('record_input_key') or 'record')


def _connect_for_payload(payload: dict):
    config = _merge_connection(payload)
    conn = connect(_database_path(config), _timeout(config))
    ensure_table(conn, _table_name(config), _fields(), _id_field())
    return conn, _table_name(config)


def _result(operation: str, success: bool, record_id: str | None = None, result: Any = None, error: str | None = None, affected_count: int = 0) -> dict:
    id_field = _id_field()
    return {'operation': operation, 'success': bool(success), 'record_id': record_id, id_field: record_id, 'result': result, 'error': error, 'affected_count': int(affected_count or 0), 'execution_time_utc': now_utc()}


def _record_from_payload(payload: dict) -> dict:
    value = payload.get(_record_key())
    if isinstance(value, dict):
        return dict(value)
    return {key: value for key, value in payload.items() if key in (RECORD_CONTRACT.get('fields') or {})}


def _id_from_payload(payload: dict) -> str | None:
    id_field = _id_field()
    for key in (id_field, 'record_id', 'id'):
        value = payload.get(key)
        if value not in (None, ''):
            return str(value)
    rec = payload.get(_record_key())
    if isinstance(rec, dict):
        value = rec.get(id_field) or rec.get('record_id') or rec.get('id')
        if value not in (None, ''):
            return str(value)
    return None


def _is_empty_filter_value(value: Any) -> bool:
    # Python-specific safe empty check. Do not write constructs such as
    # {None, "", []}; list/dict values are unhashable and valid runtime data.
    return value is None or value == "" or value == [] or value == {}


def _value_matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, list):
        expected_items = [str(x) for x in expected]
        if isinstance(actual, list):
            return any(str(item) in expected_items for item in actual)
        return str(actual) in expected_items
    if isinstance(actual, list):
        return str(expected) in [str(x) for x in actual]
    if isinstance(expected, dict):
        return json.dumps(actual, ensure_ascii=False, sort_keys=True, default=str) == json.dumps(expected, ensure_ascii=False, sort_keys=True, default=str)
    return str(actual) == str(expected)


def _apply_filters(rows: list[dict], filters: dict) -> list[dict]:
    if not isinstance(filters, dict) or not filters:
        return rows
    result = []
    for row in rows:
        ok = True
        for key, expected in filters.items():
            if _is_empty_filter_value(expected):
                continue
            actual = row.get(key)
            ok = _value_matches(actual, expected)
            if not ok:
                break
        if ok:
            result.append(row)
    return result


def create_record(operation: str, payload: dict) -> dict:
    record = _record_from_payload(payload)
    id_field = _id_field()
    required = [field for field in (RECORD_CONTRACT.get('required_fields') or []) if field != id_field]
    missing = [field for field in required if record.get(field) in (None, '')]
    if missing:
        return _result(operation, False, error='missing_required_fields: ' + ', '.join(missing))
    record_id = str(record.get(id_field) or uuid.uuid4())
    record[id_field] = record_id
    timestamp = now_utc()
    record.setdefault('created_at', timestamp)
    record['updated_at'] = timestamp
    fields = _fields()
    conn, table = _connect_for_payload(payload)
    try:
        columns = [field for field in fields if field in record]
        placeholders = ', '.join(['?'] * len(columns))
        sql = f'INSERT INTO \"{table}\" ({", ".join([chr(34)+c+chr(34) for c in columns])}) VALUES ({placeholders})'
        conn.execute(sql, [encode_value(record.get(c)) for c in columns])
        conn.commit()
        return _result(operation, True, record_id=record_id, result=record, affected_count=1)
    finally:
        conn.close()


def get_record(operation: str, payload: dict) -> dict:
    record_id = _id_from_payload(payload)
    if not record_id:
        return _result(operation, False, error='missing_record_id')
    conn, table = _connect_for_payload(payload)
    try:
        row = conn.execute(f'SELECT * FROM \"{table}\" WHERE \"{_id_field()}\" = ?', [record_id]).fetchone()
        if not row:
            return _result(operation, False, record_id=record_id, error='not_found')
        return _result(operation, True, record_id=record_id, result=row_to_dict(row), affected_count=1)
    finally:
        conn.close()


def list_records(operation: str, payload: dict) -> dict:
    limit = int(payload.get('limit') or 50)
    offset = int(payload.get('offset') or 0)
    conn, table = _connect_for_payload(payload)
    try:
        rows = [row_to_dict(row) for row in conn.execute(f'SELECT * FROM \"{table}\"').fetchall()]
        rows = _apply_filters(rows, payload.get('filters') if isinstance(payload.get('filters'), dict) else {})
        order_field = 'start_time' if 'start_time' in _fields() else ('created_at' if 'created_at' in _fields() else _id_field())
        rows.sort(key=lambda item: str(item.get(order_field) or ''))
        paged = rows[offset:offset + limit]
        return _result(operation, True, result=paged, affected_count=len(paged))
    finally:
        conn.close()


def search_records(operation: str, payload: dict) -> dict:
    query = str(payload.get('query') or '').lower()
    listed = list_records(operation, payload)
    if not listed.get('success'):
        return listed
    rows = listed.get('result') if isinstance(listed.get('result'), list) else []
    if query:
        rows = [row for row in rows if query in str(row).lower()]
    return _result(operation, True, result=rows, affected_count=len(rows))


def update_record(operation: str, payload: dict) -> dict:
    record_id = _id_from_payload(payload)
    updates = payload.get('update_fields') if isinstance(payload.get('update_fields'), dict) else {}
    if not record_id:
        return _result(operation, False, error='missing_record_id')
    if not updates:
        return _result(operation, False, record_id=record_id, error='missing_update_fields')
    updates = {key: value for key, value in updates.items() if key in _fields() and key != _id_field()}
    updates['updated_at'] = now_utc()
    conn, table = _connect_for_payload(payload)
    try:
        assignments = ', '.join([f'\"{key}\" = ?' for key in updates])
        cur = conn.execute(f'UPDATE \"{table}\" SET {assignments} WHERE \"{_id_field()}\" = ?', [encode_value(v) for v in updates.values()] + [record_id])
        conn.commit()
        if cur.rowcount <= 0:
            return _result(operation, False, record_id=record_id, error='not_found')
        return get_record(operation, payload)
    finally:
        conn.close()


def delete_record(operation: str, payload: dict) -> dict:
    record_id = _id_from_payload(payload)
    if not record_id:
        return _result(operation, False, error='missing_record_id')
    metadata = payload.get('metadata') if isinstance(payload.get('metadata'), dict) else {}
    nested = payload.get(_record_key()) if isinstance(payload.get(_record_key()), dict) else {}
    if isinstance(nested.get('metadata'), dict):
        metadata.update(nested.get('metadata'))
    force = bool(metadata.get('force_delete'))
    conn, table = _connect_for_payload(payload)
    try:
        if force or 'status' not in _fields():
            cur = conn.execute(f'DELETE FROM \"{table}\" WHERE \"{_id_field()}\" = ?', [record_id])
        else:
            cur = conn.execute(f'UPDATE \"{table}\" SET \"status\" = ?, \"updated_at\" = ? WHERE \"{_id_field()}\" = ?', ['cancelled', now_utc(), record_id])
        conn.commit()
        return _result(operation, cur.rowcount > 0, record_id=record_id, result={'deleted': force, 'soft_deleted': not force}, affected_count=cur.rowcount, error=None if cur.rowcount > 0 else 'not_found')
    finally:
        conn.close()


def execute(payload: dict | None = None) -> dict:
    payload = payload if isinstance(payload, dict) else {}
    operation = str(payload.get('operation') or '')
    if not operation:
        return _result('', False, error='missing_operation')
    kind = _operation_kinds().get(operation) or _semantic_kind(operation)
    if kind == 'create':
        return create_record(operation, payload)
    if kind == 'read_one':
        return get_record(operation, payload)
    if kind == 'read_many':
        return list_records(operation, payload)
    if kind == 'search':
        return search_records(operation, payload)
    if kind == 'update':
        return update_record(operation, payload)
    if kind == 'delete':
        return delete_record(operation, payload)
    return _result(operation, False, error='unsupported_operation')
"""

    def _contract_driven_tool_source(self, *, entrypoint: dict[str, Any]) -> str:
        fn = str(entrypoint.get("function") or "run")
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", fn):
            fn = "run"
        return f"""from __future__ import annotations

import sys
from pathlib import Path

_TOOL_DIR = Path(__file__).resolve().parent
if str(_TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOL_DIR))

from operations import execute


def _normalize_runtime_payload(payload: dict | None = None) -> dict:
    payload = payload if isinstance(payload, dict) else {{}}
    if isinstance(payload.get('input'), dict):
        merged = dict(payload.get('input') or {{}})
        for key in ('connection', '_connection', 'profile', '_profile', 'secrets', '_runtime'):
            value = payload.get(key)
            if isinstance(value, dict):
                merged[key] = value
        return merged
    return payload


def {fn}(payload: dict | None = None) -> dict:
    return execute(_normalize_runtime_payload(payload))
"""

    def _contract_driven_test_source(self, *, operation_contracts: list[dict[str, Any]], record_contract: dict[str, Any], connection_schema: dict[str, Any]) -> str:
        ops = [(str(item.get("operation")), str(item.get("semantic_kind") or self._operation_semantic_kind(str(item.get("operation"))))) for item in operation_contracts if isinstance(item, dict)]
        fields = record_contract.get("fields") if isinstance(record_contract, dict) else {}
        fields = fields if isinstance(fields, dict) else {}
        id_field = str(record_contract.get("id_field") or "record_id")
        record_key = str(record_contract.get("record_input_key") or "record")
        required = [str(x) for x in (record_contract.get("required_fields") or []) if str(x) != id_field]
        sample = {id_field: "test-record-001"}
        for field, spec in fields.items():
            if field == id_field:
                continue
            raw_ftype = spec.get("type") if isinstance(spec, dict) else "string"
            # JSON Schema type may be a list, e.g. ["array", "null"].
            # Never put raw schema values into set membership checks because
            # nested lists/dicts are valid schema data but not hashable.
            if isinstance(raw_ftype, list):
                type_names = [str(x) for x in raw_ftype if isinstance(x, str)]
                ftype = next((x for x in type_names if x != "null"), "string")
            elif isinstance(raw_ftype, str):
                ftype = raw_ftype
            else:
                ftype = "string"
            if ftype == "array":
                sample[field] = ["value"]
            elif ftype == "object":
                sample[field] = {"key": "value"}
            elif ftype == "integer" or ftype == "number":
                sample[field] = 1
            else:
                sample[field] = "value"
        for field in required:
            sample.setdefault(field, "value")
        connection_defaults = self._generic_persistence_contract(connection_schema).get("connection_defaults") or {}
        return f"""from __future__ import annotations

import tempfile
from pathlib import Path

from tool import run

OPERATIONS = {ops!r}
RECORD_KEY = {record_key!r}
ID_FIELD = {id_field!r}
SAMPLE_RECORD = {sample!r}
CONNECTION_DEFAULTS = {connection_defaults!r}


def _payload(operation: str, tmp_path: Path, **extra):
    connection = dict(CONNECTION_DEFAULTS)
    connection.setdefault('memory_database_path', str(tmp_path / 'capability_test.db'))
    connection.setdefault('database_path', str(tmp_path / 'capability_test.db'))
    connection.setdefault('table_name', 'records')
    connection.setdefault('timeout_seconds', 30)
    payload = {{'operation': operation, 'connection': connection}}
    payload.update(extra)
    return payload


def test_all_declared_operations():
    with tempfile.TemporaryDirectory() as d:
        tmp_path = Path(d)
        created_id = SAMPLE_RECORD.get(ID_FIELD) or 'test-record-001'
        for operation, kind in OPERATIONS:
            if kind == 'create':
                result = run(_payload(operation, tmp_path, **{{RECORD_KEY: dict(SAMPLE_RECORD)}}))
                assert isinstance(result, dict)
                assert result.get('success') is True, result
                created_id = result.get(ID_FIELD) or result.get('record_id') or created_id
            elif kind == 'read_one':
                result = run(_payload(operation, tmp_path, **{{ID_FIELD: created_id}}))
                assert isinstance(result, dict)
                assert 'success' in result
            elif kind == 'read_many':
                result = run(_payload(operation, tmp_path, filters={{}}))
                assert isinstance(result, dict)
                assert 'success' in result
            elif kind == 'search':
                result = run(_payload(operation, tmp_path, query='value', filters={{}}))
                assert isinstance(result, dict)
                assert 'success' in result
            elif kind == 'update':
                updates = {{k: v for k, v in SAMPLE_RECORD.items() if k != ID_FIELD}}
                if not updates:
                    updates = {{'updated_at': 'value'}}
                result = run(_payload(operation, tmp_path, **{{ID_FIELD: created_id, 'update_fields': updates}}))
                assert isinstance(result, dict)
                assert 'success' in result
            elif kind == 'delete':
                result = run(_payload(operation, tmp_path, **{{ID_FIELD: created_id}}))
                assert isinstance(result, dict)
                assert 'success' in result
            else:
                result = run(_payload(operation, tmp_path))
                assert isinstance(result, dict)
                assert 'success' in result
"""

    def _operation_coverage_violations(self, artifact: dict[str, Any], *, operation_contracts: list[dict[str, Any]], entrypoint: dict[str, Any]) -> list[str]:
        files = artifact.get("files") if isinstance(artifact, dict) else []
        text = "\n".join(str(item.get("content") or "") for item in files if isinstance(item, dict) and str(item.get("path") or "").endswith(".py"))
        violations: list[str] = []
        for item in operation_contracts:
            op = self._safe_scalar_text(item.get("operation") if isinstance(item, dict) else item)
            kind = self._safe_scalar_text(item.get("semantic_kind") if isinstance(item, dict) else "")
            if op and op not in text:
                violations.append(f"declared operation not materialized: {op}")
            if kind and kind != "custom" and kind not in text:
                violations.append(f"operation semantic kind not materialized: {op}:{kind}")
        fn = str(entrypoint.get("function") or "run") if isinstance(entrypoint, dict) else "run"
        if f"def {fn}" not in text and "def run" not in text:
            violations.append("entrypoint function not materialized")
        return violations
