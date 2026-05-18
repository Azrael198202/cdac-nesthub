from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from .blackboard import RuntimeBlackboard
from .message_bus import RuntimeMessageBus
from .models import RuntimeCommunityDefinition, RuntimeDispatchResult, RuntimeTaskDefinition


class RuntimeCommunityEngine:
    """Generic executor for runtime-generated agent communities.

    The engine does not implement domain operations. It dispatches generated
    task nodes, records neutral outputs, and exposes shared state/messages for
    external adapters or generated tools.
    """

    def __init__(
        self,
        *,
        message_bus: RuntimeMessageBus | None = None,
        blackboard: RuntimeBlackboard | None = None,
    ) -> None:
        self.message_bus = message_bus or RuntimeMessageBus()
        self.blackboard = blackboard or RuntimeBlackboard()

    def dispatch(
        self,
        definition: RuntimeCommunityDefinition,
        provided_inputs: dict[str, Any] | None = None,
    ) -> RuntimeDispatchResult:
        provided_inputs = provided_inputs or {}
        ordered_tasks = self._topological_tasks(definition)
        executed: list[str] = []
        blocked: list[str] = []
        outputs: dict[str, Any] = {}
        known_agent_ids = {agent.agent_id for agent in definition.agents}

        for task in ordered_tasks:
            if task.assigned_agent_id not in known_agent_ids:
                blocked.append(task.task_id)
                continue
            if not self._inputs_available(task, outputs, provided_inputs):
                blocked.append(task.task_id)
                continue
            output_key = task.output_ref or task.task_id
            output = {
                "task_id": task.task_id,
                "agent_id": task.assigned_agent_id,
                "status": "completed",
                "objective": task.objective,
                "inputs": {ref: outputs.get(ref, provided_inputs.get(ref)) for ref in task.input_refs},
                "parameters": task.parameters,
            }
            outputs[output_key] = output
            self.blackboard.put(output_key, task.assigned_agent_id, output)
            self.message_bus.publish(
                sender_id=task.assigned_agent_id,
                receiver_id=definition.coordinator_agent_id,
                channel="task_result",
                payload={"task_id": task.task_id, "output_ref": output_key},
            )
            executed.append(task.task_id)

        status = "completed" if not blocked else ("partial" if executed else "blocked")
        return RuntimeDispatchResult(
            community_id=definition.community_id,
            status=status,
            executed_task_ids=executed,
            blocked_task_ids=blocked,
            outputs=outputs,
            messages=self.message_bus.dump(),
        )

    def _inputs_available(
        self,
        task: RuntimeTaskDefinition,
        outputs: dict[str, Any],
        provided_inputs: dict[str, Any],
    ) -> bool:
        return all(ref in outputs or ref in provided_inputs for ref in task.input_refs)

    def _topological_tasks(self, definition: RuntimeCommunityDefinition) -> list[RuntimeTaskDefinition]:
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
        if len(ordered_ids) != len(by_id):
            return list(definition.tasks)
        return [by_id[task_id] for task_id in ordered_ids]
