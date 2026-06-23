from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import json
import re


@dataclass(frozen=True)
class CapabilityGraphNode:
    node_id: str
    stage: str
    target_file: str | None
    depends_on: list[str]
    contract: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "stage": self.stage,
            "target_file": self.target_file,
            "depends_on": list(self.depends_on),
            "contract": self.contract,
        }


class CapabilityTaskGraphCompiler:
    """Compile a capability request into a capability-neutral generation graph.

    This compiler is intentionally generic. It does not branch on capability
    names, domain words, or business scenarios. All graph nodes are derived from
    the normalized blueprint, schemas, identity contract, and runtime contracts.
    The generated graph is an execution plan for artifact generation, not a
    domain implementation template.
    """

    def compile(
        self,
        *,
        tool_id: str,
        entrypoint: dict[str, Any],
        blueprint: dict[str, Any],
        identity_contract: dict[str, Any] | None,
        input_schema: dict[str, Any],
        output_schema: dict[str, Any],
        connection_schema: dict[str, Any],
        secret_schema: dict[str, Any],
        verification_input: dict[str, Any],
        specification_contract: dict[str, Any],
    ) -> dict[str, Any]:
        identity_contract = identity_contract if isinstance(identity_contract, dict) else {}
        blueprint = blueprint if isinstance(blueprint, dict) else {}
        entrypoint = entrypoint if isinstance(entrypoint, dict) else {"module": "tool.py", "function": "run"}
        nodes: list[CapabilityGraphNode] = []

        identity = {
            "tool_id": tool_id,
            "capability_id": blueprint.get("capability_id") or blueprint.get("tool_id") or tool_id,
            "capability_name": blueprint.get("capability_name") or blueprint.get("name") or tool_id,
            "entrypoint": entrypoint,
            "identity_contract": self._compact(identity_contract),
        }
        schemas = {
            "input_schema": self._compact(input_schema),
            "output_schema": self._compact(output_schema),
            "connection_schema": self._compact(connection_schema),
            "secret_schema": self._compact(secret_schema),
            "verification_input": self._compact(verification_input),
        }
        behavior = self._behavior_contract(blueprint, input_schema=input_schema)
        runtime = {
            "dependencies": blueprint.get("dependencies") if isinstance(blueprint.get("dependencies"), list) else [],
            "runtime_execution_policy": blueprint.get("runtime_execution_policy") if isinstance(blueprint.get("runtime_execution_policy"), dict) else {},
            "approval_policy": blueprint.get("approval_policy") if isinstance(blueprint.get("approval_policy"), dict) else {},
            "verification_expectations": blueprint.get("verification_expectations") if isinstance(blueprint.get("verification_expectations"), dict) else {},
        }

        nodes.append(CapabilityGraphNode(
            node_id="identity_contract",
            stage="identity_contract",
            target_file=None,
            depends_on=[],
            contract=identity,
        ))
        nodes.append(CapabilityGraphNode(
            node_id="schema_contract",
            stage="schema_contract",
            target_file="schemas.py",
            depends_on=["identity_contract"],
            contract=schemas,
        ))

        if self._requires_separate_state_adapter(connection_schema=connection_schema, blueprint=blueprint):
            nodes.append(CapabilityGraphNode(
                node_id="state_adapter_contract",
                stage="state_adapter_contract",
                target_file="state_adapter.py",
                depends_on=["schema_contract"],
                contract={
                    "connection_schema": self._compact(connection_schema),
                    "secret_schema": self._compact(secret_schema),
                    "runtime_contract": self._compact(runtime),
                    "persistence_contract": self._compact(self._persistence_contract(blueprint, connection_schema)),
                },
            ))
            operation_deps = ["schema_contract", "state_adapter_contract"]
        else:
            operation_deps = ["schema_contract"]

        nodes.append(CapabilityGraphNode(
            node_id="operation_contract",
            stage="operation_contract",
            target_file="operations.py",
            depends_on=operation_deps,
            contract={
                "behavior_contract": behavior,
                "schemas": schemas,
                "specification_contract": self._compact(specification_contract),
            },
        ))
        nodes.append(CapabilityGraphNode(
            node_id="entrypoint_contract",
            stage="entrypoint_contract",
            target_file=str(entrypoint.get("module") or "tool.py"),
            depends_on=["operation_contract"],
            contract={
                "entrypoint": entrypoint,
                "schemas": schemas,
                "behavior_contract": behavior,
                "runtime_contract": runtime,
            },
        ))
        nodes.append(CapabilityGraphNode(
            node_id="validation_contract",
            stage="validation_contract",
            target_file="test_tool.py",
            depends_on=["entrypoint_contract"],
            contract={
                "verification_input": self._compact(verification_input),
                "verification_expectations": runtime.get("verification_expectations") or {},
                "entrypoint": entrypoint,
                "schemas": schemas,
            },
        ))

        return {
            "graph_id": self._safe_id(tool_id),
            "graph_type": "capability_artifact_generation",
            "tool_id": tool_id,
            "policy": {
                "capability_neutral": True,
                "no_domain_templates": True,
                "stage_validation_required": True,
                "repair_scope": "failed_stage_only",
            },
            "nodes": [n.to_dict() for n in nodes],
            "edges": [{"from": dep, "to": n.node_id} for n in nodes for dep in n.depends_on],
            "target_files": [n.target_file for n in nodes if n.target_file],
        }

    def _behavior_contract(self, blueprint: dict[str, Any], *, input_schema: dict[str, Any]) -> dict[str, Any]:
        raw = blueprint.get("behavior_contract") if isinstance(blueprint.get("behavior_contract"), dict) else {}
        operations = self._operation_names(blueprint, input_schema)
        requirements = []
        for key in ("requirements", "behavior_requirements", "constraints", "verification_requirements"):
            value = blueprint.get(key)
            if isinstance(value, list):
                requirements.extend([str(v) for v in value if str(v).strip()])
            elif isinstance(value, str) and value.strip():
                requirements.append(value.strip())
        return {
            "description": blueprint.get("description") or raw.get("description") or "Implement the requested runtime capability behavior from the contracts.",
            "operations": operations,
            "requirements": requirements[:120],
            "raw_behavior_contract": self._compact(raw),
        }

    def _operation_names(self, blueprint: dict[str, Any], input_schema: dict[str, Any]) -> list[str]:
        candidates: list[str] = []
        for key in ("operations", "supported_operations", "actions", "capabilities"):
            value = blueprint.get(key)
            if isinstance(value, list):
                candidates.extend([str(v) for v in value if str(v).strip()])
        props = input_schema.get("properties") if isinstance(input_schema, dict) else {}
        if isinstance(props, dict):
            for field_name in ("operation", "action", "command", "method"):
                field = props.get(field_name)
                if isinstance(field, dict):
                    enum = field.get("enum")
                    if isinstance(enum, list):
                        candidates.extend([str(v) for v in enum if str(v).strip()])
        seen: set[str] = set()
        out: list[str] = []
        for item in candidates:
            normalized = re.sub(r"[^a-zA-Z0-9_\-:.]", "_", item.strip())[:120]
            if normalized and normalized not in seen:
                seen.add(normalized)
                out.append(normalized)
        return out

    def _requires_separate_state_adapter(self, *, connection_schema: dict[str, Any], blueprint: dict[str, Any]) -> bool:
        props = connection_schema.get("properties") if isinstance(connection_schema, dict) else {}
        if isinstance(props, dict) and props:
            return True
        policy = blueprint.get("runtime_execution_policy") if isinstance(blueprint.get("runtime_execution_policy"), dict) else {}
        return bool(policy.get("stateful") or policy.get("requires_storage"))

    def _persistence_contract(self, blueprint: dict[str, Any], connection_schema: dict[str, Any]) -> dict[str, Any]:
        contract = blueprint.get("persistence_contract") if isinstance(blueprint.get("persistence_contract"), dict) else {}
        return {
            "declared": self._compact(contract),
            "connection_schema": self._compact(connection_schema),
            "rule": "Use only values supplied through runtime connection/input contracts. Do not embed business data or secrets in generated code.",
        }

    def _compact(self, value: Any, *, limit: int = 5000) -> Any:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            text = str(value)
        if len(text) <= limit:
            return value
        return {"_truncated_json": text[:limit], "_original_length": len(text)}

    def _safe_id(self, value: str) -> str:
        safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(value or "capability")).strip("._-")
        return safe or "capability"
