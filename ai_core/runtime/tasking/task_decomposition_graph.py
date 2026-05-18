from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True)
class TaskNode:
    """A runtime-neutral work item created from a user request."""

    task_id: str
    objective: str
    task_type: str = "information_unit"
    depends_on: tuple[str, ...] = ()
    required_outputs: tuple[str, ...] = ()
    parameters: dict[str, Any] = field(default_factory=dict)
    can_run_parallel: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "objective": self.objective,
            "task_type": self.task_type,
            "depends_on": list(self.depends_on),
            "required_outputs": list(self.required_outputs),
            "parameters": dict(self.parameters),
            "can_run_parallel": self.can_run_parallel,
        }


class QueryDecomposer:
    """Builds neutral sub-queries without embedding any domain vocabulary."""

    _split_pattern = re.compile(r"(?:\n+|[;；]|(?:\s+and\s+)|(?:\s+plus\s+)|(?:、)|(?:，)|(?:,))", re.IGNORECASE)

    def decompose(self, request: str, requested_dimensions: Iterable[str] | None = None) -> list[TaskNode]:
        text = " ".join(str(request or "").split())
        dimensions = [str(x).strip() for x in (requested_dimensions or []) if str(x).strip()]
        if not dimensions:
            dimensions = self._infer_dimensions(text)
        if not dimensions:
            dimensions = [text or "complete_request"]

        nodes: list[TaskNode] = []
        for index, dimension in enumerate(dict.fromkeys(dimensions), start=1):
            objective = self._compose_objective(text, dimension)
            nodes.append(
                TaskNode(
                    task_id=self._stable_id("task", index, objective),
                    objective=objective,
                    task_type="retrieve_or_compute",
                    required_outputs=("evidence", "facts", "confidence"),
                    parameters={"query": objective, "dimension": dimension},
                    can_run_parallel=True,
                )
            )

        synthesis_id = self._stable_id("task", len(nodes) + 1, text + ":synthesis")
        nodes.append(
            TaskNode(
                task_id=synthesis_id,
                objective="Synthesize verified task outputs into a coherent final response.",
                task_type="synthesis",
                depends_on=tuple(node.task_id for node in nodes),
                required_outputs=("final_answer", "confidence", "coverage"),
                parameters={"source_request": text},
                can_run_parallel=False,
            )
        )
        return nodes

    def _infer_dimensions(self, text: str) -> list[str]:
        chunks = [part.strip() for part in self._split_pattern.split(text or "") if part.strip()]
        if len(chunks) <= 1:
            return []
        return [chunk[:120] for chunk in chunks]

    def _compose_objective(self, request: str, dimension: str) -> str:
        if request and dimension and dimension not in request:
            return f"{request} :: {dimension}"
        return dimension or request or "complete_request"

    def _stable_id(self, prefix: str, index: int, value: str) -> str:
        digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
        return f"{prefix}_{index:02d}_{digest}"


class TaskDecompositionGraph:
    """Represents a dependency graph that can identify parallel batches."""

    def build(self, request: str, requested_dimensions: Iterable[str] | None = None) -> dict[str, Any]:
        nodes = QueryDecomposer().decompose(request, requested_dimensions)
        graph = {node.task_id: node for node in nodes}
        return {
            "version": "2.1",
            "nodes": [node.to_dict() for node in nodes],
            "edges": [
                {"from": dep, "to": node.task_id}
                for node in nodes
                for dep in node.depends_on
            ],
            "parallel_batches": self.parallel_batches(graph),
        }

    def parallel_batches(self, graph: dict[str, TaskNode]) -> list[list[str]]:
        remaining = set(graph.keys())
        completed: set[str] = set()
        batches: list[list[str]] = []
        while remaining:
            ready = sorted(
                task_id for task_id in remaining
                if set(graph[task_id].depends_on).issubset(completed)
            )
            if not ready:
                raise ValueError("Task graph contains a dependency cycle.")
            batches.append(ready)
            completed.update(ready)
            remaining.difference_update(ready)
        return batches
