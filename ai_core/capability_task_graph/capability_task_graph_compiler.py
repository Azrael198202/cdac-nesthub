from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any


class CapabilityTaskGraphCompiler:
    """Compile one long capability acquisition blueprint into small stages.

    Boundary:
    - Does not know business domains.
    - Does not generate concrete domain logic.
    - Treats names, fields, operations, and storage contracts as opaque values
      extracted from the user-derived blueprint/schema contract.
    """

    DEFAULT_STAGES = [
        "identity_contract",
        "schema_contract",
        "storage_contract",
        "operation_contract",
        "approval_contract",
        "artifact_scaffold",
        "operation_generation",
        "sandbox_validation",
        "registry_registration",
    ]

    def compile(
        self,
        *,
        tool_id: str,
        blueprint: dict[str, Any],
        identity_contract: dict[str, Any] | None = None,
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
        connection_schema: dict[str, Any] | None = None,
        secret_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        blueprint = blueprint if isinstance(blueprint, dict) else {}
        identity_contract = identity_contract if isinstance(identity_contract, dict) else {}
        text = json.dumps(blueprint, ensure_ascii=False, default=str)
        operation_names = self._operation_names(input_schema or {}, text)
        record_fields = self._record_fields(input_schema or {}, text)
        table_fields = self._table_fields(text) or [{"name": name, "type": "TEXT"} for name in record_fields]
        nodes = []
        dependencies: list[str] = []
        for stage in self.DEFAULT_STAGES:
            node_id = stage
            nodes.append(
                {
                    "id": node_id,
                    "stage": stage,
                    "depends_on": list(dependencies[-1:]),
                    "status": "pending",
                    "contract_ref": f"contracts/{stage}.json",
                }
            )
            dependencies.append(node_id)
        return {
            "graph_id": f"capability_task_graph:{tool_id}",
            "tool_id": tool_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "nodes": nodes,
            "contracts": {
                "identity_contract": {
                    "tool_id": tool_id,
                    "identity": identity_contract,
                    "blueprint_identity": {k: blueprint.get(k) for k in ("capability_id", "capability_name", "tool_id", "template_id") if k in blueprint},
                },
                "schema_contract": {
                    "input_schema": input_schema or {},
                    "output_schema": output_schema or {},
                    "connection_schema": connection_schema or {},
                    "secret_schema": secret_schema or {},
                },
                "storage_contract": {
                    "record_fields": record_fields,
                    "table_fields": table_fields,
                    "storage_backend": "local_runtime_database",
                },
                "operation_contract": {
                    "operation_names": operation_names,
                    "operation_classes": self._operation_classes(operation_names),
                },
                "approval_contract": blueprint.get("approval_policy") if isinstance(blueprint.get("approval_policy"), dict) else {},
            },
            "execution_policy": {
                "mode": "stage_by_stage",
                "llm_scope": "small_stage_only",
                "deterministic_scaffold_allowed": True,
                "repair_scope": "failed_stage_only",
            },
        }

    def _operation_names(self, input_schema: dict[str, Any], text: str) -> list[str]:
        props = input_schema.get("properties") if isinstance(input_schema.get("properties"), dict) else {}
        operation = props.get("operation") if isinstance(props.get("operation"), dict) else {}
        enum = operation.get("enum") if isinstance(operation.get("enum"), list) else []
        names = [str(x).strip() for x in enum if str(x).strip()]
        if names:
            return names
        matches = re.findall(r"\b([a-zA-Z_]+(?:create|read|get|list|search|update|delete)[a-zA-Z_]*)\b", text, flags=re.I)
        seen: set[str] = set()
        result: list[str] = []
        for match in matches:
            key = match.strip()
            if key and key not in seen:
                seen.add(key)
                result.append(key)
        return result or ["create", "get", "list", "search", "update", "delete"]

    def _operation_classes(self, names: list[str]) -> dict[str, str]:
        classes: dict[str, str] = {}
        for name in names:
            lower = name.casefold()
            if "create" in lower or "add" in lower or "insert" in lower:
                classes[name] = "create"
            elif "get" in lower or "read" in lower:
                classes[name] = "get"
            elif "list" in lower:
                classes[name] = "list"
            elif "search" in lower or "find" in lower or "query" in lower:
                classes[name] = "search"
            elif "update" in lower or "change" in lower or "modify" in lower:
                classes[name] = "update"
            elif "delete" in lower or "remove" in lower:
                classes[name] = "delete"
            else:
                classes[name] = "unknown"
        return classes

    def _record_fields(self, input_schema: dict[str, Any], text: str) -> list[str]:
        props = input_schema.get("properties") if isinstance(input_schema.get("properties"), dict) else {}
        for holder_name in ("record", "item", "entity", "schedule", "data"):
            holder = props.get(holder_name)
            if isinstance(holder, dict) and isinstance(holder.get("properties"), dict):
                return [str(k) for k in holder["properties"].keys()]
        fields: list[str] = []
        seen: set[str] = set()
        for match in re.findall(r"^[ \t]*[*-][ \t]*([A-Za-z_][A-Za-z0-9_]*)\b", text, flags=re.M):
            name = match.strip()
            if name and name not in seen:
                seen.add(name)
                fields.append(name)
        return fields[:80]

    def _table_fields(self, text: str) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        seen: set[str] = set()
        for match in re.findall(r"^[ \t]*[*-][ \t]*([A-Za-z_][A-Za-z0-9_]*)[ \t]+(TEXT|INTEGER|REAL|BLOB|NUMERIC)([^\n]*)", text, flags=re.M | re.I):
            name, typ, suffix = match
            name = name.strip()
            if name in seen:
                continue
            seen.add(name)
            rows.append({"name": name, "type": typ.upper(), "constraints": str(suffix or "").strip()})
        return rows[:80]
