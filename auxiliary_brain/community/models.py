from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RuntimeAgentDefinition:
    """A runtime-generated participant definition.

    The core stores only neutral metadata. Concrete role labels,
    instructions, and capability labels are produced at runtime and persisted
    outside ai_core.
    """

    agent_id: str
    role_label: str
    capability_labels: list[str] = field(default_factory=list)
    instruction_ref: str | None = None
    memory_ref: str | None = None
    tool_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "role_label": self.role_label,
            "capability_labels": list(self.capability_labels),
            "instruction_ref": self.instruction_ref,
            "memory_ref": self.memory_ref,
            "tool_refs": list(self.tool_refs),
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class RuntimeActivation:
    """A neutral activation rule for a generated task graph."""

    activation_id: str
    mode: str
    expression: str
    timezone: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "activation_id": self.activation_id,
            "mode": self.mode,
            "expression": self.expression,
            "timezone": self.timezone,
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class RuntimeTaskEdge:
    """Dependency edge between two generated tasks."""

    from_task_id: str
    to_task_id: str
    condition: str = "completed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_task_id": self.from_task_id,
            "to_task_id": self.to_task_id,
            "condition": self.condition,
        }


@dataclass(slots=True)
class RuntimeTaskDefinition:
    """A runtime-generated task node.

    Payload fields are intentionally open-ended so generated definitions can
    represent any domain without changing core code.
    """

    task_id: str
    assigned_agent_id: str
    objective: str
    input_refs: list[str] = field(default_factory=list)
    output_ref: str | None = None
    activation_ref: str | None = None
    requires_approval: bool = False
    parameters: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "assigned_agent_id": self.assigned_agent_id,
            "objective": self.objective,
            "input_refs": list(self.input_refs),
            "output_ref": self.output_ref,
            "activation_ref": self.activation_ref,
            "requires_approval": self.requires_approval,
            "parameters": dict(self.parameters),
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class RuntimeCommunityDefinition:
    """Runtime-generated group of agents and task graph."""

    community_id: str
    coordinator_agent_id: str
    agents: list[RuntimeAgentDefinition] = field(default_factory=list)
    activations: list[RuntimeActivation] = field(default_factory=list)
    tasks: list[RuntimeTaskDefinition] = field(default_factory=list)
    edges: list[RuntimeTaskEdge] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "community_id": self.community_id,
            "coordinator_agent_id": self.coordinator_agent_id,
            "agents": [agent.to_dict() for agent in self.agents],
            "activations": [activation.to_dict() for activation in self.activations],
            "tasks": [task.to_dict() for task in self.tasks],
            "edges": [edge.to_dict() for edge in self.edges],
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class RuntimeDispatchResult:
    """Execution result for a generated task graph."""

    community_id: str
    status: str
    executed_task_ids: list[str] = field(default_factory=list)
    blocked_task_ids: list[str] = field(default_factory=list)
    outputs: dict[str, Any] = field(default_factory=dict)
    messages: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "community_id": self.community_id,
            "status": self.status,
            "executed_task_ids": list(self.executed_task_ids),
            "blocked_task_ids": list(self.blocked_task_ids),
            "outputs": dict(self.outputs),
            "messages": list(self.messages),
        }
