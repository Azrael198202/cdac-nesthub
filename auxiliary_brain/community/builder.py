from __future__ import annotations

from typing import Any
from uuid import uuid4

from .models import (
    RuntimeActivation,
    RuntimeAgentDefinition,
    RuntimeCommunityDefinition,
    RuntimeTaskDefinition,
    RuntimeTaskEdge,
)


def _safe_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class RuntimeCommunityBuilder:
    """Builds generic community definitions from generated specifications."""

    def build(self, specification: dict[str, Any]) -> RuntimeCommunityDefinition:
        community_id = specification.get("community_id") or _safe_id("community")
        agent_specs = list(specification.get("agents") or [])
        if not agent_specs:
            agent_specs = [{"role_label": "coordinator", "capability_labels": ["coordination"]}]
        agents: list[RuntimeAgentDefinition] = []
        for index, item in enumerate(agent_specs):
            agent_id = item.get("agent_id") or f"agent_{index + 1}"
            agents.append(
                RuntimeAgentDefinition(
                    agent_id=agent_id,
                    role_label=str(item.get("role_label") or f"role_{index + 1}"),
                    capability_labels=[str(value) for value in item.get("capability_labels", [])],
                    instruction_ref=item.get("instruction_ref"),
                    memory_ref=item.get("memory_ref"),
                    tool_refs=[str(value) for value in item.get("tool_refs", [])],
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        coordinator_agent_id = specification.get("coordinator_agent_id") or agents[0].agent_id
        activations = [
            RuntimeActivation(
                activation_id=str(item.get("activation_id") or f"activation_{index + 1}"),
                mode=str(item.get("mode") or "manual"),
                expression=str(item.get("expression") or "manual"),
                timezone=item.get("timezone"),
                metadata=dict(item.get("metadata") or {}),
            )
            for index, item in enumerate(specification.get("activations") or [])
        ]
        tasks = [
            RuntimeTaskDefinition(
                task_id=str(item.get("task_id") or f"task_{index + 1}"),
                assigned_agent_id=str(item.get("assigned_agent_id") or coordinator_agent_id),
                objective=str(item.get("objective") or "generated objective"),
                input_refs=[str(value) for value in item.get("input_refs", [])],
                output_ref=item.get("output_ref"),
                activation_ref=item.get("activation_ref"),
                requires_approval=bool(item.get("requires_approval", False)),
                parameters=dict(item.get("parameters") or {}),
                metadata=dict(item.get("metadata") or {}),
            )
            for index, item in enumerate(specification.get("tasks") or [])
        ]
        edges = [
            RuntimeTaskEdge(
                from_task_id=str(item.get("from_task_id")),
                to_task_id=str(item.get("to_task_id")),
                condition=str(item.get("condition") or "completed"),
            )
            for item in specification.get("edges") or []
            if item.get("from_task_id") and item.get("to_task_id")
        ]
        return RuntimeCommunityDefinition(
            community_id=community_id,
            coordinator_agent_id=coordinator_agent_id,
            agents=agents,
            activations=activations,
            tasks=tasks,
            edges=edges,
            metadata=dict(specification.get("metadata") or {}),
        )
