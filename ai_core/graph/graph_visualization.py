from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import re


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
    PASSIVE = {"pending", "ready", "waiting", "waiting_input", "metadata_only"}

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
        label = self._display_label(task, fallback=node_id)
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
        label = self._display_label(node, fallback=node_id)
        kind = str(node.get("node_type") or node.get("kind") or node.get("task_type") or "runtime_node")
        return {
            "id": node_id,
            "label": label[:120],
            "kind": kind,
            "status": status_by_node.get(node_id, self._normalize_status(node.get("status"))),
            "summary": str(node.get("summary") or node.get("notes") or node.get("description") or "")[:240],
            "has_output": bool(node.get("output") or node.get("result") or node.get("artifact_ref")),
        }


    def _display_label(self, item: dict[str, Any], *, fallback: str) -> str:
        """Return a short UI label without leaking long instruction text.

        Graph nodes should be recognizable runtime actors or generated step
        titles.  Full user instructions remain available as summaries/details.
        """
        priority = (
            "participant_display_name",
            "display_name",
            "participant_name",
            "agent_name",
            "role_name",
            "label",
            "name",
            "title",
            "source_step_id",
            "task_id",
        )
        for key in priority:
            value = str(item.get(key) or "").strip()
            if value:
                return self._compact_label(value)
        return self._compact_label(fallback)

    def _compact_label(self, value: str) -> str:
        text = re.sub(r"\s+", " ", str(value or "").strip())
        if not text:
            return "runtime_node"
        words = text.split(" ")
        if len(words) > 8:
            text = " ".join(words[:8]) + " …"
        return text[:80]

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
        """Resolve node status from graph, scheduler summary, and live run payload.

        The graph file is mostly static and often keeps every node as pending.
        Runtime state is stored separately in the run payload.  The visualizer
        therefore overlays live result and progress evidence on top of the
        static graph definition.  This method only reads structural identifiers,
        statuses, and telemetry events; it does not depend on task vocabulary.
        """
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

        # Overlay completed/failed participant results by participant_id.
        for item in self._as_list(run.get("agent_results")):
            if not isinstance(item, dict):
                continue
            node_id = str(item.get("participant_id") or item.get("id") or "").strip()
            if not node_id:
                continue
            statuses[node_id] = self._normalize_status(item.get("status"))

        # Overlay live progress events.  The static graph stores node ids as
        # participant ids, while progress events are stage labels.  Map them
        # through agent_results and the graph's task ordering when possible.
        id_by_index = self._node_ids_by_participant_index(nodes)
        for event in self._as_list(run.get("progress_events")) + self._as_list(run.get("primary_runtime_events")):
            if not isinstance(event, dict):
                continue
            status = self._normalize_status(event.get("status"))
            if status not in {"running", "completed", "failed", "skipped", "reused", "repair", "waiting", "waiting_input"}:
                continue
            target_ids = self._event_target_node_ids(event, id_by_index, nodes)
            for node_id in target_ids:
                if not node_id:
                    continue
                previous = statuses.get(node_id, "pending")
                # Preserve terminal failures; otherwise let newer telemetry win.
                if previous == "failed" and status != "failed":
                    continue
                statuses[node_id] = "waiting_input" if status in {"waiting", "waiting_input"} else status

        run_status = self._normalize_status(run.get("status"))
        if run_status == "waiting_input":
            unresolved = [node_id for node_id, status in statuses.items() if status in {"pending", "ready"}]
            if len(unresolved) == 1:
                statuses[unresolved[0]] = "waiting_input"

        # Once a run is terminal, static graph nodes that produced agent_results
        # are already covered above.  Any remaining pending downstream nodes with
        # failed upstreams should be visible as skipped instead of stale pending.
        edge_list = self._extract_edges({"nodes": nodes}, run)
        failed = {node_id for node_id, status in statuses.items() if status == "failed"}
        if failed:
            changed = True
            while changed:
                changed = False
                for edge in edge_list:
                    src = str(edge.get("from") or edge.get("source") or edge.get("source_id") or "").strip()
                    dst = str(edge.get("to") or edge.get("target") or edge.get("target_id") or "").strip()
                    if src in failed and dst and statuses.get(dst) != "failed":
                        statuses[dst] = "failed"
                        failed.add(dst)
                        changed = True
        return statuses

    def _node_ids_by_participant_index(self, nodes: list[dict[str, Any]]) -> dict[int, str]:
        ids: dict[int, str] = {}
        for index, node in enumerate(nodes, start=1):
            node_id = self._node_id(node, index - 1)
            ids[index] = node_id
        return ids

    def _event_target_node_ids(self, event: dict[str, Any], id_by_index: dict[int, str], nodes: list[dict[str, Any]] | None = None) -> list[str]:
        direct = str(event.get("participant_id") or event.get("node_id") or event.get("id") or "").strip()
        known = set(id_by_index.values())
        if direct and (direct in known or not known):
            return [direct]
        stage = str(event.get("stage") or "")
        message = str(event.get("message") or event.get("title") or "")
        candidates: list[str] = []
        for pattern in (r"participant_(\d+)", r"node_(\d+)"):
            match = re.search(pattern, stage)
            if match:
                node_id = id_by_index.get(int(match.group(1)))
                if node_id:
                    candidates.append(node_id)
        # Some runtime telemetry is emitted with user-visible participant names
        # rather than stable ids (for example "Preparing participant: X").
        # Map by structural labels from the selected graph without relying on
        # task-specific vocabulary.
        if nodes:
            haystack = f"{stage} {message}".casefold()
            for idx, node in enumerate(nodes):
                node_id = self._node_id(node, idx)
                labels = [
                    node_id,
                    str(node.get("participant_id") or ""),
                    str(node.get("participant_name") or ""),
                    str(node.get("agent_name") or ""),
                    str(node.get("display_name") or ""),
                    str(node.get("name") or ""),
                    str(node.get("label") or ""),
                ]
                for label in labels:
                    normalized = str(label or "").strip().casefold()
                    if normalized and normalized in haystack:
                        candidates.append(node_id)
                        break
        # Preserve order while deduplicating.
        out: list[str] = []
        for item in candidates:
            if item and item not in out:
                out.append(item)
        return out

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
        events = (
            self._as_list(summary.get("history"))
            + self._as_list(run.get("events"))
            + self._as_list(run.get("progress_events"))
            + self._as_list(run.get("primary_runtime_events"))
        )
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
        """Select only the run that belongs to the selected graph.

        Runtime visualization must not reuse a previous run only because node
        labels or participant names are similar.  A newly created graph with no
        run must remain pending/created until a run with the same graph id or
        task name exists.
        """
        dicts = [r for r in runs if isinstance(r, dict)]
        matched = [
            r for r in dicts
            if str(r.get("graph_id") or "") == graph_id
            or str(r.get("task_graph_id") or "") == graph_id
            or str(r.get("task_name") or "") == graph_id
        ]
        matched.sort(key=lambda item: str(item.get("completed_at") or item.get("started_at") or item.get("updated_at") or ""))
        return matched[-1] if matched else None

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
        if value in {"requires_input", "requires_key", "paused", "waiting_for_input", "waiting_input", "human_input_required"}:
            return "waiting_input"
        if value in {"reused", "cached", "reuse"}:
            return "reused"
        if value in self.PASSIVE:
            return value
        return "pending"

    def _as_list(self, value: Any) -> list[Any]:
        return value if isinstance(value, list) else []
