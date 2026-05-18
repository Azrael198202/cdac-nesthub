from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable
from uuid import uuid4


@dataclass(slots=True)
class RuntimeWorkflowNode:
    node_id: str
    node_type: str
    operation: str
    input_refs: list[str] = field(default_factory=list)
    output_ref: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "operation": self.operation,
            "input_refs": list(self.input_refs),
            "output_ref": self.output_ref,
            "parameters": dict(self.parameters),
        }


class RuntimeWorkflowExecutor:
    """Generic execution DAG runner used by the main brain.

    The class knows only neutral execution concepts: prepare, collect,
    validate, synthesize. Concrete capabilities and surface labels come from
    runtime-generated agent/task metadata or configuration files.
    """

    ORIGIN = "ai_core"

    def build_collect_plan(self, *, operation: str, query: str, task_id: str, agent_id: str) -> dict[str, Any]:
        workflow_id = f"workflow_{uuid4().hex[:8]}"
        nodes = [
            RuntimeWorkflowNode(
                node_id=f"{workflow_id}_prepare",
                node_type="prepare",
                operation="normalize_runtime_request",
                output_ref="prepared_request",
                parameters={"task_id": task_id, "agent_id": agent_id, "operation": operation, "query": query},
            ),
            RuntimeWorkflowNode(
                node_id=f"{workflow_id}_collect",
                node_type="collect",
                operation=operation,
                input_refs=["prepared_request"],
                output_ref="collected_material",
                parameters={"query": query},
            ),
            RuntimeWorkflowNode(
                node_id=f"{workflow_id}_validate",
                node_type="validate",
                operation="validate_collected_material",
                input_refs=["collected_material"],
                output_ref="validated_material",
            ),
        ]
        return {"workflow_id": workflow_id, "origin": self.ORIGIN, "nodes": [node.to_dict() for node in nodes], "edges": self._edges(nodes)}

    def build_synthesis_plan(self, *, input_refs: list[str], task_id: str, agent_id: str) -> dict[str, Any]:
        workflow_id = f"workflow_{uuid4().hex[:8]}"
        nodes = [
            RuntimeWorkflowNode(
                node_id=f"{workflow_id}_prepare",
                node_type="prepare",
                operation="normalize_runtime_inputs",
                output_ref="prepared_inputs",
                parameters={"task_id": task_id, "agent_id": agent_id, "input_refs": list(input_refs)},
            ),
            RuntimeWorkflowNode(
                node_id=f"{workflow_id}_synthesize",
                node_type="synthesize",
                operation="stable_synthesis",
                input_refs=["prepared_inputs"],
                output_ref="final_material",
            ),
        ]
        return {"workflow_id": workflow_id, "origin": self.ORIGIN, "nodes": [node.to_dict() for node in nodes], "edges": self._edges(nodes)}

    def run_collect_plan(
        self,
        *,
        plan: dict[str, Any],
        operation: str,
        query: str,
        collectors: dict[str, Callable[[str], dict[str, Any]]],
        context_supplier: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        outputs: dict[str, Any] = {}
        events: list[dict[str, Any]] = []
        final_material: dict[str, Any] = {}
        for node in plan.get("nodes", []):
            node_id = str(node.get("node_id"))
            node_type = str(node.get("node_type"))
            node_operation = str(node.get("operation"))
            status = "completed"
            if node_type == "prepare":
                material = {"status": "prepared", "query": query, "operation": operation}
            elif node_type == "collect" and operation == "runtime_context_snapshot":
                material = context_supplier()
            elif node_type == "collect":
                collector = collectors.get(operation) or collectors.get("public_discovery")
                material = collector(query) if collector else {"status": "skipped", "reason": "no_collector"}
            elif node_type == "validate":
                material = self._validate_material(outputs.get("collected_material", {}))
            else:
                status = "skipped"
                material = {"status": "skipped", "reason": "unsupported_node"}
            outputs[str(node.get("output_ref") or node_id)] = material
            if node_type in {"collect", "validate"}:
                final_material = material
            events.append(self._event(node_id, node_type, node_operation, status, material))
        return {"workflow_plan": plan, "workflow_outputs": outputs, "execution_events": events, "final_material": final_material}

    def run_synthesis_plan(self, *, plan: dict[str, Any], fragments: list[str], synthesizer: Callable[[list[str]], str]) -> dict[str, Any]:
        outputs: dict[str, Any] = {}
        events: list[dict[str, Any]] = []
        final_text = ""
        for node in plan.get("nodes", []):
            node_id = str(node.get("node_id"))
            node_type = str(node.get("node_type"))
            node_operation = str(node.get("operation"))
            if node_type == "prepare":
                material: Any = {"status": "prepared", "fragment_count": len(fragments)}
            elif node_type == "synthesize":
                final_text = synthesizer(fragments)
                material = {"status": "completed", "result_text": final_text, "fragment_count": len(fragments)}
            else:
                material = {"status": "skipped"}
            outputs[str(node.get("output_ref") or node_id)] = material
            events.append(self._event(node_id, node_type, node_operation, str(material.get("status", "completed")) if isinstance(material, dict) else "completed", material))
        return {"workflow_plan": plan, "workflow_outputs": outputs, "execution_events": events, "result_text": final_text}

    def _validate_material(self, material: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(material, dict):
            return {"status": "failed", "passed": False, "reason": "material_not_object"}
        signals = []
        if material.get("result_text"):
            signals.append("result_text")
        if material.get("results"):
            signals.append("result_list")
        if material.get("selected_document"):
            signals.append("selected_document")
        passed = bool(signals) or material.get("status") in {"success", "completed"}
        return {"status": "completed", "passed": passed, "signals": signals, "material_status": material.get("status")}

    def _edges(self, nodes: list[RuntimeWorkflowNode]) -> list[dict[str, str]]:
        return [
            {"from_node_id": nodes[index].node_id, "to_node_id": nodes[index + 1].node_id, "condition": "completed"}
            for index in range(len(nodes) - 1)
        ]

    def _event(self, node_id: str, node_type: str, operation: str, status: str, material: Any) -> dict[str, Any]:
        return {
            "event_id": f"event_{uuid4().hex[:8]}",
            "origin": self.ORIGIN,
            "node_id": node_id,
            "node_type": node_type,
            "operation": operation,
            "status": status,
            "summary": self._summarize(material),
            "created_at": datetime.now().astimezone().isoformat(),
        }

    def _summarize(self, material: Any) -> str:
        text = str(material if not isinstance(material, dict) else material.get("result_text") or material.get("query") or material.get("status") or material)
        return " ".join(text.split())[:240]
