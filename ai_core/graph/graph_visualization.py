from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GraphVisualState:
    """UI-ready graph state for runtime visualization."""

    graph_id: str
    status: str
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    lanes: list[list[str]]
    events: list[dict[str, Any]]
    summary: dict[str, Any]
    repair_plan: list[dict[str, Any]]


class GraphVisualStateBuilder:
    """Builds a domain-neutral DAG snapshot for UI rendering.

    The builder only interprets structural runtime fields such as nodes, edges,
    status, history, outputs, and repair records. It intentionally avoids task
    vocabulary and domain-specific decisions.
    """

    TERMINAL_SUCCESS = {"completed", "passed", "succeeded", "ok", "done"}
    TERMINAL_FAILURE = {"failed", "error", "blocked"}
    ACTIVE = {"running", "executing", "in_progress"}
    PASSIVE = {"pending", "ready", "waiting", "metadata_only"}

    def from_partition(
        self,
        *,
        graph_id: str,
        partition: Any,
        scheduler_summary: dict[str, Any] | None = None,
        self_check: dict[str, Any] | None = None,
    ) -> GraphVisualState:
        execution = getattr(partition, "execution_graph", {}) if partition is not None else {}
        metadata = getattr(partition, "metadata_graph", {}) if partition is not None else {}
        dataflow = getattr(partition, "dataflow_graph", {}) if partition is not None else {}
        nodes = self._as_list(execution.get("nodes")) + self._as_list(metadata.get("nodes"))
        edges = self._as_list(dataflow.get("edges")) + self._as_list(metadata.get("edges"))
        return self.from_graph(
            graph={"graph_id": graph_id, "nodes": nodes, "edges": edges},
            run={"scheduler_summary": scheduler_summary or {}, "self_check": self_check or {}},
        )

    def from_snapshot(self, snapshot: dict[str, Any] | None, graph_id: str | None = None) -> GraphVisualState:
        snapshot = snapshot if isinstance(snapshot, dict) else {}
        graphs = self._as_list(snapshot.get("task_graphs"))
        runs = self._as_list(snapshot.get("task_runs"))
        selected_graph = self._select_graph(graphs, graph_id)
        selected_id = self._graph_id(selected_graph) if selected_graph else str(graph_id or "runtime_graph")
        selected_run = self._select_run(runs, selected_id)
        return self.from_graph(graph=selected_graph or {"graph_id": selected_id, "nodes": [], "edges": []}, run=selected_run or {})

    def from_graph(self, graph: dict[str, Any] | None, run: dict[str, Any] | None = None) -> GraphVisualState:
        graph = graph if isinstance(graph, dict) else {}
        run = run if isinstance(run, dict) else {}
        graph_id = self._graph_id(graph)
        scheduler_summary = self._summary_from_run(run)
        self_check = self._self_check_from_run(run)
        raw_nodes = self._extract_nodes(graph, run)
        raw_edges = self._extract_edges(graph, run)
        status_by_node = self._status_by_node(raw_nodes, scheduler_summary, run)
        nodes = [self._visual_node(node, index, status_by_node) for index, node in enumerate(raw_nodes)]
        node_ids = {str(node.get("id")) for node in nodes}
        edges = [self._visual_edge(edge, index, status_by_node) for index, edge in enumerate(raw_edges)]
        edges = [edge for edge in edges if edge.get("from") in node_ids and edge.get("to") in node_ids]
        lanes = self._topological_lanes(nodes, edges)
        events = self._events(scheduler_summary, run, self_check)
        status = self._overall_status(nodes, scheduler_summary, self_check, run)
        return GraphVisualState(
            graph_id=graph_id,
            status=status,
            nodes=nodes,
            edges=edges,
            lanes=lanes,
            events=events,
            summary={
                "node_count": len(nodes),
                "edge_count": len(edges),
                "lane_count": len(lanes),
                "completed_count": len([n for n in nodes if n.get("status") == "completed"]),
                "running_count": len([n for n in nodes if n.get("status") == "running"]),
                "failed_count": len([n for n in nodes if n.get("status") == "failed"]),
                "skipped_count": len([n for n in nodes if n.get("status") == "skipped"]),
                "reused_count": len([n for n in nodes if n.get("status") == "reused"]),
                "repair_count": len(self._repair_plan(self_check, run)),
            },
            repair_plan=self._repair_plan(self_check, run),
        )

    def to_dict(self, state: GraphVisualState) -> dict[str, Any]:
        return {
            "ok": True,
            "graph_id": state.graph_id,
            "status": state.status,
            "nodes": state.nodes,
            "edges": state.edges,
            "lanes": state.lanes,
            "events": state.events,
            "summary": state.summary,
            "repair_plan": state.repair_plan,
        }

    def _extract_nodes(self, graph: dict[str, Any], run: dict[str, Any]) -> list[dict[str, Any]]:
        task_values = self._as_list(graph.get("tasks"))
        if task_values:
            return [self._task_as_node(task, index) for index, task in enumerate(task_values) if isinstance(task, dict)]
        candidates = [
            graph.get("nodes"),
            graph.get("steps"),
            graph.get("planned_steps"),
            graph.get("execution_graph", {}).get("nodes") if isinstance(graph.get("execution_graph"), dict) else None,
            run.get("nodes"),
            run.get("steps"),
        ]
        for item in candidates:
            values = self._as_list(item)
            if values:
                return [node for node in values if isinstance(node, dict)]
        return []

    def _task_as_node(self, task: dict[str, Any], index: int) -> dict[str, Any]:
        node_id = str(task.get("participant_id") or task.get("node_id") or task.get("id") or task.get("task_id") or f"task_{index + 1}").strip()
        label = str(
            task.get("label")
            or task.get("display_name")
            or task.get("participant_name")
            or task.get("source_instruction_fragment")
            or task.get("source_step_id")
            or task.get("task_id")
            or node_id
        )
        return {
            **task,
            "node_id": node_id,
            "id": node_id,
            "label": label,
            "kind": task.get("step_type") or task.get("task_type") or "runtime_step",
        }

    def _extract_edges(self, graph: dict[str, Any], run: dict[str, Any]) -> list[dict[str, Any]]:
        candidates = [
            graph.get("edges"),
            graph.get("dataflow_edges"),
            graph.get("dataflow_graph", {}).get("edges") if isinstance(graph.get("dataflow_graph"), dict) else None,
            run.get("edges"),
        ]
        for item in candidates:
            values = self._as_list(item)
            if values:
                return [edge for edge in values if isinstance(edge, dict)]
        nodes = self._extract_nodes(graph, run)
        generated: list[dict[str, Any]] = []
        for node in nodes:
            target = self._node_id(node, len(generated))
            for upstream in self._as_list(node.get("depends_on")):
                if isinstance(upstream, str) and upstream.strip():
                    generated.append({"from": upstream.strip(), "to": target, "data_contract": "runtime_json"})
        return generated

    def _visual_node(self, node: dict[str, Any], index: int, status_by_node: dict[str, str]) -> dict[str, Any]:
        node_id = self._node_id(node, index)
        label = str(node.get("label") or node.get("name") or node.get("title") or node.get("objective") or node_id)
        kind = str(node.get("node_type") or node.get("kind") or node.get("task_type") or "runtime_node")
        return {
            "id": node_id,
            "label": label[:120],
            "kind": kind,
            "status": status_by_node.get(node_id, self._normalize_status(node.get("status"))),
            "summary": str(node.get("summary") or node.get("notes") or node.get("description") or "")[:240],
            "has_output": bool(node.get("output") or node.get("result") or node.get("artifact_ref")),
        }

    def _visual_edge(self, edge: dict[str, Any], index: int, status_by_node: dict[str, str]) -> dict[str, Any]:
        source = str(edge.get("from") or edge.get("source") or edge.get("source_id") or "").strip()
        target = str(edge.get("to") or edge.get("target") or edge.get("target_id") or "").strip()
        source_status = status_by_node.get(source, "pending")
        target_status = status_by_node.get(target, "pending")
        status = "pending"
        if target_status == "skipped":
            status = "skipped"
        elif source_status == "failed" or target_status == "failed":
            status = "failed"
        elif source_status in {"completed", "reused"} and target_status in {"completed", "running", "reused"}:
            status = "transferred"
        elif source_status == "running":
            status = "active"
        return {
            "id": str(edge.get("edge_id") or edge.get("id") or f"edge_{index + 1}"),
            "from": source,
            "to": target,
            "label": str(edge.get("label") or edge.get("data_contract") or "runtime_json")[:80],
            "status": status,
        }

    def _status_by_node(self, nodes: list[dict[str, Any]], summary: dict[str, Any], run: dict[str, Any]) -> dict[str, str]:
        statuses: dict[str, str] = {}
        for node in nodes:
            statuses[self._node_id(node, len(statuses))] = self._normalize_status(node.get("status"))
        for name in self._as_list(summary.get("completed")):
            statuses[str(name)] = "completed"
        for name in self._as_list(summary.get("running")):
            statuses[str(name)] = "running"
        for name in self._as_list(summary.get("failed")):
            statuses[str(name)] = "failed"
        for name in self._as_list(summary.get("skipped")):
            statuses[str(name)] = "skipped"
        for name in self._as_list(summary.get("pending")):
            statuses.setdefault(str(name), "pending")
        for name in self._as_list(run.get("reused_nodes")) + self._as_list(summary.get("reused")):
            statuses[str(name)] = "reused"
        return statuses

    def _topological_lanes(self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[list[str]]:
        ids = [str(node.get("id")) for node in nodes]
        upstream: dict[str, set[str]] = {node_id: set() for node_id in ids}
        downstream: dict[str, set[str]] = {node_id: set() for node_id in ids}
        for edge in edges:
            src = str(edge.get("from") or "")
            dst = str(edge.get("to") or "")
            if src in upstream and dst in upstream:
                upstream[dst].add(src)
                downstream[src].add(dst)
        remaining = set(ids)
        completed: set[str] = set()
        lanes: list[list[str]] = []
        while remaining:
            ready = sorted([node_id for node_id in remaining if upstream[node_id].issubset(completed)])
            if not ready:
                ready = sorted(remaining)
            lanes.append(ready)
            remaining.difference_update(ready)
            completed.update(ready)
        return lanes

    def _overall_status(self, nodes: list[dict[str, Any]], summary: dict[str, Any], self_check: dict[str, Any], run: dict[str, Any]) -> str:
        if self._repair_plan(self_check, run):
            return "repair"
        node_statuses = {str(n.get("status")) for n in nodes}
        if "failed" in node_statuses or summary.get("status") in self.TERMINAL_FAILURE:
            return "failed"
        if "running" in node_statuses or summary.get("status") in self.ACTIVE:
            return "running"
        if "skipped" in node_statuses:
            return "skipped"
        if nodes and all(str(n.get("status")) in {"completed", "reused", "metadata_only"} for n in nodes):
            return "completed"
        return self._normalize_status(run.get("status") or summary.get("status") or "pending")

    def _events(self, summary: dict[str, Any], run: dict[str, Any], self_check: dict[str, Any]) -> list[dict[str, Any]]:
        events = self._as_list(summary.get("history")) + self._as_list(run.get("events"))
        if self._repair_plan(self_check, run):
            events.append({"event": "repair_available", "count": len(self._repair_plan(self_check, run))})
        return [event for event in events if isinstance(event, dict)][-80:]

    def _repair_plan(self, self_check: dict[str, Any], run: dict[str, Any]) -> list[dict[str, Any]]:
        plan = self_check.get("repair_plan") if isinstance(self_check, dict) else None
        if not isinstance(plan, list):
            plan = run.get("repair_plan") if isinstance(run, dict) else None
        return [item for item in plan if isinstance(item, dict)] if isinstance(plan, list) else []

    def _summary_from_run(self, run: dict[str, Any]) -> dict[str, Any]:
        for key in ("scheduler_summary", "graph_summary", "summary"):
            value = run.get(key)
            if isinstance(value, dict):
                return value
        return {}

    def _self_check_from_run(self, run: dict[str, Any]) -> dict[str, Any]:
        for key in ("self_check", "graph_self_check", "validation"):
            value = run.get(key)
            if isinstance(value, dict):
                return value
        return {}

    def _select_graph(self, graphs: list[Any], graph_id: str | None) -> dict[str, Any] | None:
        dicts = [g for g in graphs if isinstance(g, dict)]
        if graph_id:
            for graph in dicts:
                if self._graph_id(graph) == graph_id:
                    return graph
        return dicts[-1] if dicts else None

    def _select_run(self, runs: list[Any], graph_id: str) -> dict[str, Any] | None:
        dicts = [r for r in runs if isinstance(r, dict)]
        matched = [r for r in dicts if str(r.get("graph_id") or r.get("task_name") or r.get("run_id") or "") == graph_id]
        candidates = matched or dicts
        candidates.sort(key=lambda item: str(item.get("completed_at") or item.get("started_at") or item.get("updated_at") or ""))
        return candidates[-1] if candidates else None

    def _graph_id(self, graph: dict[str, Any]) -> str:
        return str(graph.get("graph_id") or graph.get("task_name") or graph.get("id") or "runtime_graph")

    def _node_id(self, node: dict[str, Any], index: int) -> str:
        return str(node.get("node_id") or node.get("id") or node.get("task_id") or node.get("name") or f"node_{index + 1}").strip()

    def _normalize_status(self, status: Any) -> str:
        value = str(status or "pending").strip().lower()
        if value in self.TERMINAL_SUCCESS:
            return "completed"
        if value in self.TERMINAL_FAILURE:
            return "failed"
        if value in self.ACTIVE:
            return "running"
        if value in {"skip", "skipped", "cancelled"}:
            return "skipped"
        if value in {"reused", "cached", "reuse"}:
            return "reused"
        if value in self.PASSIVE:
            return value
        return "pending"

    def _as_list(self, value: Any) -> list[Any]:
        return value if isinstance(value, list) else []
