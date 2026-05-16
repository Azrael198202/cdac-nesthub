from __future__ import annotations

from typing import Any


class SequenceSynthesizer:
    """Creates an ordered execution or response sequence from graph dependencies."""

    def synthesize(self, graph: dict[str, Any], weights: dict[str, float] | None = None) -> dict[str, Any]:
        weights = weights or {}
        nodes = {node["task_id"]: node for node in graph.get("nodes", [])}
        batches = graph.get("parallel_batches") or []
        ordered: list[dict[str, Any]] = []
        position = 1
        for batch in batches:
            ranked = sorted(batch, key=lambda task_id: weights.get(task_id, 0), reverse=True)
            for task_id in ranked:
                if task_id in nodes:
                    item = dict(nodes[task_id])
                    item["sequence_index"] = position
                    ordered.append(item)
                    position += 1
        return {"sequence": ordered, "count": len(ordered)}
