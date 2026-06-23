from __future__ import annotations

from typing import Any


class CapabilityStageExecutor:
    """Minimal stage executor contract used by auxiliary_brain integrations."""

    def mark_completed(self, graph: dict[str, Any], stage: str, result: dict[str, Any] | None = None) -> dict[str, Any]:
        graph = graph if isinstance(graph, dict) else {}
        for node in graph.get("nodes", []) if isinstance(graph.get("nodes"), list) else []:
            if isinstance(node, dict) and node.get("stage") == stage:
                node["status"] = "completed"
                node["result"] = result or {}
        return graph
