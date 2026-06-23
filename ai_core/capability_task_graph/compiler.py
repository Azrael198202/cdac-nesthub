from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ai_core.safe_collections import safe_dedupe, safe_hashable, safe_json_key, safe_string_list


class CapabilityTaskGraphCompiler:
    """Compile a capability acquisition contract into generic generation stages.

    This compiler is capability-neutral. It never branches on domain/capability
    names. It reads the runtime contracts supplied by ai_core and turns them into
    small, inspectable nodes that auxiliary_brain can execute and validate.
    """

    def compile(
        self,
        *,
        tool_id: str,
        entrypoint: dict[str, Any] | None,
        blueprint: dict[str, Any] | None,
        identity_contract: dict[str, Any] | None,
        input_schema: dict[str, Any] | None,
        output_schema: dict[str, Any] | None,
        connection_schema: dict[str, Any] | None,
        secret_schema: dict[str, Any] | None,
        verification_input: dict[str, Any] | None,
        specification_contract: dict[str, Any] | None,
    ) -> dict[str, Any]:
        blueprint = blueprint if isinstance(blueprint, dict) else {}
        identity_contract = identity_contract if isinstance(identity_contract, dict) else {}
        entrypoint = entrypoint if isinstance(entrypoint, dict) else {"module": "tool.py", "function": "run"}
        entrypoint.setdefault("module", "tool.py")
        entrypoint.setdefault("function", "run")

        input_schema = input_schema if isinstance(input_schema, dict) else {}
        output_schema = output_schema if isinstance(output_schema, dict) else {}
        connection_schema = connection_schema if isinstance(connection_schema, dict) else {}
        secret_schema = secret_schema if isinstance(secret_schema, dict) else {}
        verification_input = verification_input if isinstance(verification_input, dict) else {}
        specification_contract = specification_contract if isinstance(specification_contract, dict) else {}

        operation_contracts = self._operation_contracts(input_schema=input_schema, specification_contract=specification_contract)
        record_contract = self._record_contract(input_schema=input_schema, specification_contract=specification_contract)
        persistence_contract = self._persistence_contract(connection_schema=connection_schema, specification_contract=specification_contract)

        stages: list[dict[str, Any]] = [
            {
                "node_id": "contract_normalization",
                "stage": "contract_normalization",
                "target_file": "contract.json",
                "generator": "deterministic_contract_materializer",
                "goal": "Normalize identity, schemas, persistence contract, operation contract, and verification input from user-derived runtime contracts.",
                "validation": ["json_serializable", "operation_contract_complete", "schema_contract_complete"],
                "inputs": ["identity", "input_schema", "output_schema", "connection_schema", "secret_schema", "verification_input", "specification_contract"],
            },
            {
                "node_id": "schema_contract",
                "stage": "schema_contract",
                "target_file": "schemas.py",
                "generator": "contract_driven_code_generator",
                "goal": "Materialize schema constants and lightweight validation helpers from the supplied runtime contract.",
                "validation": ["python_syntax", "json_serializable_constants", "schema_defaults_preserved"],
                "inputs": ["input_schema", "output_schema", "connection_schema", "secret_schema", "record_contract", "operation_contracts"],
            },
            {
                "node_id": "storage_contract",
                "stage": "storage_contract",
                "target_file": "storage.py",
                "generator": "contract_driven_code_generator",
                "goal": "Materialize a generic persistence adapter from the supplied persistence contract.",
                "validation": ["python_syntax", "storage_adapter_importable", "no_external_dependency"],
                "inputs": ["connection_schema", "persistence_contract", "record_contract"],
            },
            {
                "node_id": "operation_contract",
                "stage": "operation_contract",
                "target_file": "operations.py",
                "generator": "contract_driven_code_generator",
                "goal": "Materialize operation dispatch and operation handlers from operation contracts inferred from the runtime input schema.",
                "validation": ["python_syntax", "all_declared_operations_implemented", "operation_dispatch_complete"],
                "inputs": ["operation_contracts", "record_contract", "persistence_contract", "output_schema"],
                "operation_contracts": operation_contracts,
            },
            {
                "node_id": "runtime_entrypoint",
                "stage": "runtime_entrypoint",
                "target_file": str(entrypoint.get("module") or "tool.py"),
                "generator": "contract_driven_code_generator",
                "goal": "Materialize the runtime entrypoint that validates payload, loads connection/profile values, dispatches operations, and returns structured JSON.",
                "validation": ["python_syntax", "entrypoint_function_exists", "json_serializable_output", "all_declared_operations_reachable"],
                "inputs": ["schemas", "storage", "operations", "operation_contracts", "verification_input"],
            },
            {
                "node_id": "local_validation",
                "stage": "local_validation",
                "target_file": "test_tool.py",
                "generator": "contract_driven_test_generator",
                "goal": "Materialize local sandbox tests that execute every declared operation without live external dependencies.",
                "validation": ["python_syntax", "pytest_or_direct_execution", "all_declared_operations_tested"],
                "inputs": ["operation_contracts", "verification_input", "output_schema"],
            },
        ]
        if operation_contracts:
            for index, op in enumerate(operation_contracts, start=1):
                stages.append(
                    {
                        "node_id": f"operation_validation_{index:03d}",
                        "stage": "operation_validation",
                        "target_file": f"validation/operation_{index:03d}.json",
                        "generator": "deterministic_operation_validation",
                        "goal": "Validate one declared operation against the generated runtime entrypoint.",
                        "validation": ["operation_executed", "structured_output", "success_or_explicit_error"],
                        "operation": op,
                    }
                )

        return {
            "graph_id": f"capability_task_graph::{tool_id}",
            "kind": "capability_acquisition_task_graph",
            "tool_id": tool_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "entrypoint": entrypoint,
            "contracts": {
                "identity": identity_contract,
                "input_schema": input_schema,
                "output_schema": output_schema,
                "connection_schema": connection_schema,
                "secret_schema": secret_schema,
                "verification_input": verification_input,
                "specification_contract": specification_contract,
                "operation_contracts": operation_contracts,
                "record_contract": record_contract,
                "persistence_contract": persistence_contract,
                "blueprint_summary": {
                    "capability_id": blueprint.get("capability_id") or blueprint.get("tool_id") or tool_id,
                    "capability_name": blueprint.get("capability_name") or blueprint.get("name") or "",
                    "description": blueprint.get("description") or "",
                },
            },
            "nodes": stages,
            "edges": self._edges(stages),
            "execution_policy": {
                "mode": "sequential",
                "fail_fast": False,
                "repair_scope": "current_node_only",
                "fallback_to_full_artifact_generation": False,
                "requires_operation_coverage": True,
            },
        }

    def _edges(self, stages: list[dict[str, Any]]) -> list[dict[str, str]]:
        edges: list[dict[str, str]] = []
        previous = None
        for node in stages:
            node_id = str(node.get("node_id") or "")
            if previous and node_id:
                edges.append({"from": previous, "to": node_id})
            if node_id:
                previous = node_id
        return edges

    def _schema_properties(self, schema: dict[str, Any]) -> dict[str, Any]:
        props = schema.get("properties") if isinstance(schema, dict) else {}
        return props if isinstance(props, dict) else {}


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

    def _operation_contracts(self, *, input_schema: dict[str, Any], specification_contract: dict[str, Any]) -> list[dict[str, Any]]:
        props = self._schema_properties(input_schema)
        op_schema = props.get("operation") if isinstance(props.get("operation"), dict) else {}
        enum_values = op_schema.get("enum") if isinstance(op_schema, dict) else []
        if not isinstance(enum_values, list):
            enum_values = []
        ops = self._safe_unique_texts(enum_values)
        if not ops:
            candidates: list[Any] = []
            for key in ("supported_operations", "operations", "operation_contracts"):
                value = specification_contract.get(key) if isinstance(specification_contract, dict) else None
                if isinstance(value, list):
                    candidates.extend(value)
                elif value is not None:
                    candidates.append(value)
            ops = self._safe_unique_texts(candidates)
        contracts: list[dict[str, Any]] = []
        for name in ops:
            contracts.append({"operation": name, "semantic_kind": self._semantic_kind(name), "source": "input_schema.operation.enum"})
        return contracts

    def _semantic_kind(self, operation: str) -> str:
        normalized = str(operation or "").strip().lower()
        prefix = normalized.split("_", 1)[0]
        mapping = {
            "create": "create",
            "add": "create",
            "insert": "create",
            "get": "read_one",
            "read": "read_one",
            "retrieve": "read_one",
            "list": "read_many",
            "search": "search",
            "find": "search",
            "update": "update",
            "modify": "update",
            "patch": "update",
            "delete": "delete",
            "remove": "delete",
            "cancel": "delete",
        }
        return mapping.get(prefix, "custom")

    def _record_contract(self, *, input_schema: dict[str, Any], specification_contract: dict[str, Any]) -> dict[str, Any]:
        props = self._schema_properties(input_schema)
        reserved = {"operation", "query", "filters", "update_fields", "limit", "offset", "profile", "connection", "secrets", "_runtime"}
        object_fields: dict[str, Any] = {}
        object_name = "record"
        for key, value in props.items():
            if key in reserved or not isinstance(value, dict):
                continue
            if value.get("type") == "object" and isinstance(value.get("properties"), dict):
                object_name = key
                object_fields = value.get("properties") or {}
                break
        if not object_fields:
            object_fields = {k: v for k, v in props.items() if k not in reserved and isinstance(v, dict)}
        id_field = "record_id"
        for key in object_fields.keys():
            lowered = str(key).lower()
            if lowered == "id" or lowered.endswith("_id"):
                id_field = str(key)
                break
        required = []
        object_schema = props.get(object_name) if isinstance(props.get(object_name), dict) else {}
        if isinstance(object_schema.get("required"), list):
            required = [str(x) for x in object_schema.get("required")]
        elif isinstance(input_schema.get("required"), list):
            required = [str(x) for x in input_schema.get("required") if str(x) in object_fields]
        return {
            "record_input_key": object_name,
            "id_field": id_field,
            "fields": object_fields,
            "required_fields": required,
            "reserved_input_fields": sorted(reserved),
        }

    def _persistence_contract(self, *, connection_schema: dict[str, Any], specification_contract: dict[str, Any]) -> dict[str, Any]:
        props = self._schema_properties(connection_schema)
        defaults: dict[str, Any] = {}
        for key, value in props.items():
            if isinstance(value, dict) and "default" in value:
                defaults[key] = value.get("default")
        return {
            "engine": "sqlite_standard_library",
            "connection_defaults": defaults,
            "database_path_keys": [k for k in props.keys() if "path" in str(k).lower() or "database" in str(k).lower() or "db" in str(k).lower()],
            "table_name_keys": [k for k in props.keys() if "table" in str(k).lower()],
            "timeout_keys": [k for k in props.keys() if "timeout" in str(k).lower()],
        }
