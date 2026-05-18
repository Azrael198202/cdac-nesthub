from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

Retriever = Callable[[dict[str, Any]], Awaitable[dict[str, Any]] | dict[str, Any]]


@dataclass(frozen=True)
class RetrievalResult:
    task_id: str
    status: str
    material: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"task_id": self.task_id, "status": self.status, "material": self.material}


class ParallelRetrievalRuntime:
    """Runs independent retrieval work concurrently with deterministic result ordering."""

    async def run(self, tasks: list[dict[str, Any]], retrievers: list[Retriever]) -> list[dict[str, Any]]:
        if not retrievers:
            raise ValueError("At least one retriever is required.")
        jobs = [self._run_one(task, retrievers) for task in tasks if task.get("can_run_parallel", True)]
        results = await asyncio.gather(*jobs)
        return [result.to_dict() for result in sorted(results, key=lambda item: item.task_id)]

    async def _run_one(self, task: dict[str, Any], retrievers: list[Retriever]) -> RetrievalResult:
        materials: list[dict[str, Any]] = []
        for retriever in retrievers:
            try:
                value = retriever(task)
                if asyncio.iscoroutine(value):
                    value = await value
                if isinstance(value, dict):
                    materials.append(value)
            except Exception as exc:  # pragma: no cover - defensive path
                materials.append({"status": "failed", "error_type": exc.__class__.__name__, "message": str(exc)})
        status = "success" if any(m.get("status") in {"success", "ok"} for m in materials) else "partial"
        return RetrievalResult(task_id=str(task.get("task_id", "unknown")), status=status, material={"sources": materials})
