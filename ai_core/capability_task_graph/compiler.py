from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class CapabilityTaskGraphCompiler:
    """Compile a capability acquisition contract into generic generation stages.

    This compiler is intentionally capability-neutral. It does not branch on
    domain words or capability ids. It turns runtime contracts into small,
    inspectable stage nodes that the auxiliary brain can execute one at a time.
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
        stages = [
            {
                "node_id": "schema_contract",
                "stage": "schema_contract",
                "target_file": "schemas.py",
                "goal": "Materialize schema and contract constants only from the supplied runtime contract.",
                "validation": ["python_syntax", "json_serializable_constants"],
                "inputs": ["input_schema", "output_schema", "connection_schema", "secret_schema"],
            },
            {
                "node_id": "runtime_entrypoint",
                "stage": "runtime_entrypoint",
                "target_file": str(entrypoint.get("module") or "tool.py"),
                "goal": "Generate the executable runtime entrypoint from the supplied schemas, behavior contract, and verification contract.",
                "validation": ["python_syntax", "entrypoint_function_exists", "json_serializable_output"],
                "inputs": ["schemas", "behavior_contract", "verification_input", "specification_contract"],
            },
            {
                "node_id": "local_validation",
                "stage": "local_validation",
                "target_file": "test_tool.py",
                "goal": "Generate local sandbox tests for the runtime entrypoint without external live dependencies.",
                "validation": ["python_syntax", "pytest_or_direct_execution"],
                "inputs": ["target_file", "verification_input", "output_schema"],
            },
        ]
        return {
            "graph_id": f"capability_task_graph::{tool_id}",
            "kind": "capability_acquisition_task_graph",
            "tool_id": tool_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "entrypoint": entrypoint,
            "contracts": {
                "identity": identity_contract,
                "input_schema": input_schema or {},
                "output_schema": output_schema or {},
                "connection_schema": connection_schema or {},
                "secret_schema": secret_schema or {},
                "verification_input": verification_input or {},
                "specification_contract": specification_contract or {},
                "blueprint_summary": {
                    "capability_id": blueprint.get("capability_id") or blueprint.get("tool_id") or tool_id,
                    "capability_name": blueprint.get("capability_name") or blueprint.get("name") or "",
                    "description": blueprint.get("description") or "",
                },
            },
            "nodes": stages,
            "edges": [
                {"from": "schema_contract", "to": "runtime_entrypoint"},
                {"from": "runtime_entrypoint", "to": "local_validation"},
            ],
            "execution_policy": {
                "mode": "sequential",
                "fail_fast": False,
                "repair_scope": "current_node_only",
                "fallback_to_full_artifact_generation": False,
            },
        }
