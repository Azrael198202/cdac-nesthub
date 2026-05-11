from __future__ import annotations

from typing import Any

try:
    from langgraph.graph import StateGraph
except Exception:  # pragma: no cover
    StateGraph = None


class _FallbackGraph:
    def __init__(self) -> None:
        self.nodes: list[str] = []
        self.edges: list[tuple[str, str]] = []

    def add_node(self, node_id: str) -> None:
        self.nodes.append(node_id)

    def add_edge(self, source: str, target: str) -> None:
        self.edges.append((source, target))

    def compile(self) -> "_FallbackGraph":
        return self


class GraphBuilder:
    def build(self, workflow: dict[str, Any]):
        graph = StateGraph(dict) if StateGraph is not None else _FallbackGraph()
        nodes = workflow.get("nodes", [])

        for node in nodes:
            graph.add_node(node["id"])

        existing_ids = {node["id"] for node in nodes}
        for node in nodes:
            next_node = node.get("next")
            if not next_node:
                continue
            targets = next_node if isinstance(next_node, list) else [next_node]
            for target in targets:
                if target in existing_ids:
                    graph.add_edge(node["id"], target)

        return graph.compile()
