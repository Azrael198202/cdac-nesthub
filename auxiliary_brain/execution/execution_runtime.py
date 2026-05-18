from __future__ import annotations

import json
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from auxiliary_brain.community.builder import RuntimeCommunityBuilder
from auxiliary_brain.community.models import RuntimeAgentDefinition, RuntimeCommunityDefinition, RuntimeTaskDefinition
from auxiliary_brain.execution.tool_runtime import RuntimeToolRuntime
from auxiliary_brain.observability import RuntimeTraceLogger
from auxiliary_brain.scheduler.scheduler_runtime import RuntimeScheduler


class RuntimeExecutionRuntime:
    """Run generated task graphs as live execution instances."""

    ORIGIN = "auxiliary_brain"

    def __init__(self, runtime_root: str | Path = "runtime") -> None:
        self.runtime_root = Path(runtime_root)
        self.builder = RuntimeCommunityBuilder()
        self.scheduler = RuntimeScheduler(runtime_root)
        self.tools = RuntimeToolRuntime(runtime_root)
        self.trace_logger = RuntimeTraceLogger(runtime_root)
        self.run_dir = self.runtime_root / "generated" / "task_runs"
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def register_graph(self, *, graph_payload: dict[str, Any], graph_path: str | Path) -> dict[str, Any]:
        graph_id = self._graph_id(graph_payload)
        activation = (graph_payload.get("activations") or [{}])[0]
        registration = self.scheduler.register(graph_id=graph_id, graph_path=str(graph_path), activation=activation)
        self._write_run(graph_id, registration["schedule"].get("status", "registered"), {"registration": registration})
        self.trace_logger.record(
            origin=self.ORIGIN,
            event_type="live_execution_registered",
            payload={"graph_id": graph_id, "schedule_id": registration["schedule"].get("schedule_id"), "status": registration["schedule"].get("status")},
        )
        return registration

    def run_due(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for record in self.scheduler.due_records():
            schedule_id = record.get("schedule_id")
            if not schedule_id:
                continue
            self.scheduler.mark(schedule_id, "running", {"reason": "due"})
            result = self.execute_graph_file(record.get("graph_path", ""), schedule_id=schedule_id)
            self.scheduler.mark(schedule_id, result.get("status", "completed"), result)
            results.append(result)
        return results

    def execute_graph_file(self, graph_path: str | Path, *, schedule_id: str | None = None) -> dict[str, Any]:
        path = Path(graph_path)
        if not path.exists():
            return {"origin": self.ORIGIN, "status": "missing_graph", "graph_path": str(path)}
        payload = json.loads(path.read_text(encoding="utf-8"))
        definition = self.builder.build(payload)
        return self.execute_definition(definition, graph_path=str(path), schedule_id=schedule_id)

    def execute_definition(self, definition: RuntimeCommunityDefinition, *, graph_path: str = "", schedule_id: str | None = None) -> dict[str, Any]:
        graph_id = definition.metadata.get("graph_id") or definition.community_id
        ordered_tasks = self._ordered_tasks(definition)
        agents = {agent.agent_id: agent for agent in definition.agents}
        outputs: dict[str, Any] = {}
        executed: list[str] = []
        blocked: list[str] = []
        for task in ordered_tasks:
            agent = agents.get(task.assigned_agent_id)
            if not agent:
                blocked.append(task.task_id)
                continue
            task_inputs = {ref: outputs[ref] for ref in task.input_refs if ref in outputs}
            if len(task_inputs) != len(task.input_refs):
                blocked.append(task.task_id)
                continue
            output = self.tools.execute(task=task, agent=agent, inputs=task_inputs)
            outputs[task.output_ref or task.task_id] = output
            executed.append(task.task_id)
        status = "completed" if not blocked else ("partial" if executed else "blocked")
        delivery = self.tools.deliver(graph_id=str(graph_id), content={"status": status, "outputs": outputs}) if executed else {}
        result = {
            "run_id": f"run_{uuid4().hex[:8]}",
            "origin": self.ORIGIN,
            "graph_id": graph_id,
            "graph_path": graph_path,
            "schedule_id": schedule_id,
            "status": status,
            "executed_task_ids": executed,
            "blocked_task_ids": blocked,
            "outputs": outputs,
            "delivery": delivery,
            "created_at": self._now(),
        }
        self._write_run(str(graph_id), status, result)
        self.trace_logger.record(
            origin=self.ORIGIN,
            event_type="live_execution_completed",
            payload={"graph_id": graph_id, "status": status, "executed_count": len(executed), "blocked_count": len(blocked), "delivery": delivery.get("artifact_path")},
        )
        return result

    def _ordered_tasks(self, definition: RuntimeCommunityDefinition) -> list[RuntimeTaskDefinition]:
        by_id = {task.task_id: task for task in definition.tasks}
        incoming: dict[str, int] = {task_id: 0 for task_id in by_id}
        outgoing: dict[str, list[str]] = defaultdict(list)
        for edge in definition.edges:
            if edge.from_task_id in by_id and edge.to_task_id in by_id:
                outgoing[edge.from_task_id].append(edge.to_task_id)
                incoming[edge.to_task_id] += 1
        queue = deque([task_id for task_id, count in incoming.items() if count == 0])
        ordered_ids: list[str] = []
        while queue:
            task_id = queue.popleft()
            ordered_ids.append(task_id)
            for next_id in outgoing[task_id]:
                incoming[next_id] -= 1
                if incoming[next_id] == 0:
                    queue.append(next_id)
        return [by_id[task_id] for task_id in ordered_ids] if len(ordered_ids) == len(by_id) else list(definition.tasks)

    def _write_run(self, graph_id: str, status: str, payload: dict[str, Any]) -> Path:
        data = {"graph_id": graph_id, "origin": self.ORIGIN, "status": status, "updated_at": self._now(), "payload": payload}
        path = self.run_dir / f"{graph_id}.json"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _graph_id(self, payload: dict[str, Any]) -> str:
        return str((payload.get("metadata") or {}).get("graph_id") or payload.get("community_id") or f"graph_{uuid4().hex[:8]}")

    def _now(self) -> str:
        return datetime.now().astimezone().isoformat()
