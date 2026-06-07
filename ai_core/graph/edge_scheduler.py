from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SchedulerState:
    pending: set[str] = field(default_factory=set)
    running: set[str] = field(default_factory=set)
    completed: set[str] = field(default_factory=set)
    failed: set[str] = field(default_factory=set)
    skipped: set[str] = field(default_factory=set)
    outputs: dict[str, Any] = field(default_factory=dict)
    bound_inputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)


class EdgeDrivenScheduler:
    """Schedules executable nodes by dataflow edges.

    The scheduler exposes deterministic operations for: ready nodes, execution
    start, output binding, downstream unlock, failure marking, and terminal
    summary. It does not execute node logic and does not know domain semantics.
    """

    def create_state(self, execution_graph: dict[str, Any], dataflow_graph: dict[str, Any]) -> SchedulerState:
        node_ids = [self._node_id(node) for node in self._nodes(execution_graph)]
        state = SchedulerState(pending={node_id for node_id in node_ids if node_id})
        state.history.append({"event": "scheduler_initialized", "pending": sorted(state.pending)})
        return state

    def ready_nodes(self, execution_graph: dict[str, Any], dataflow_graph: dict[str, Any], state: SchedulerState) -> list[dict[str, Any]]:
        completed = set(state.completed)
        blocked = set(state.running) | set(state.failed) | set(state.skipped)
        ready: list[dict[str, Any]] = []
        for node in self._nodes(execution_graph):
            node_id = self._node_id(node)
            if node_id not in state.pending or node_id in blocked:
                continue
            upstream = self.upstream_ids(node_id, dataflow_graph)
            if upstream.issubset(completed):
                ready.append(node)
        return ready

    def mark_started(self, node_id: str, state: SchedulerState) -> None:
        node_id = str(node_id)
        if node_id in state.pending:
            state.pending.remove(node_id)
        state.running.add(node_id)
        state.history.append({"event": "node_started", "node_id": node_id})

    def bind_output(self, node_id: str, output: Any, dataflow_graph: dict[str, Any], state: SchedulerState) -> dict[str, Any]:
        node_id = str(node_id)
        state.running.discard(node_id)
        state.completed.add(node_id)
        state.outputs[node_id] = output
        bindings: dict[str, Any] = {}
        for edge in self._edges(dataflow_graph):
            if str(edge.get("from") or "") != node_id:
                continue
            target_id = str(edge.get("to") or "")
            if not target_id:
                continue
            target_inputs = state.bound_inputs.setdefault(target_id, {})
            target_inputs[node_id] = {
                "from": node_id,
                "data_contract": edge.get("data_contract") or "runtime_json",
                "value": output,
            }
            bindings[target_id] = target_inputs[node_id]
        state.history.append({"event": "node_completed", "node_id": node_id, "unlocked_candidates": sorted(bindings)})
        return bindings

    def mark_failed(self, node_id: str, reason: str, dataflow_graph: dict[str, Any], state: SchedulerState) -> list[str]:
        node_id = str(node_id)
        state.pending.discard(node_id)
        state.running.discard(node_id)
        state.failed.add(node_id)
        affected: set[str] = set()
        stack = [node_id]
        while stack:
            current = stack.pop()
            for downstream in self.downstream_ids(current, dataflow_graph):
                if downstream in affected:
                    continue
                affected.add(downstream)
                stack.append(downstream)
        for downstream in affected:
            if downstream in state.pending:
                state.pending.remove(downstream)
                state.skipped.add(downstream)
        state.history.append({"event": "node_failed", "node_id": node_id, "reason": str(reason), "affected": sorted(affected)})
        return sorted(affected)

    def is_terminal(self, state: SchedulerState) -> bool:
        return not state.pending and not state.running

    def summary(self, state: SchedulerState) -> dict[str, Any]:
        status = "completed" if not state.failed and not state.pending and not state.running else "incomplete"
        if state.failed:
            status = "failed"
        return {
            "status": status,
            "pending": sorted(state.pending),
            "running": sorted(state.running),
            "completed": sorted(state.completed),
            "failed": sorted(state.failed),
            "skipped": sorted(state.skipped),
            "bound_inputs": state.bound_inputs,
            "history": state.history,
        }

    def upstream_ids(self, node_id: str, dataflow_graph: dict[str, Any]) -> set[str]:
        return {str(edge.get("from")) for edge in self._edges(dataflow_graph) if str(edge.get("to") or "") == str(node_id)}

    def downstream_ids(self, node_id: str, dataflow_graph: dict[str, Any]) -> set[str]:
        return {str(edge.get("to")) for edge in self._edges(dataflow_graph) if str(edge.get("from") or "") == str(node_id)}

    def _nodes(self, graph: dict[str, Any]) -> list[dict[str, Any]]:
        nodes = graph.get("nodes") if isinstance(graph, dict) else []
        return [node for node in nodes if isinstance(node, dict)] if isinstance(nodes, list) else []

    def _edges(self, graph: dict[str, Any]) -> list[dict[str, Any]]:
        edges = graph.get("edges") if isinstance(graph, dict) else []
        return [edge for edge in edges if isinstance(edge, dict)] if isinstance(edges, list) else []

    def _node_id(self, node: dict[str, Any]) -> str:
        return str(node.get("node_id") or node.get("id") or node.get("name") or "").strip()
