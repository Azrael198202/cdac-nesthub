from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class PrimaryRuntimeExecutionPolicy:
    """Policy passed from the auxiliary layer to the primary runtime.

    The fields are generic runtime controls.  They do not describe any business
    domain.  The primary runtime may use them to decide whether to auto-approve
    read-only steps, generate missing capabilities, call MCP, or escalate models.
    """

    auto_approve_read_only: bool = True
    allow_external_sources: bool = True
    allow_capability_generation: bool = True
    allow_mcp: bool = True
    allow_cli: bool = True
    allow_model_escalation: bool = True
    require_final_user_answer: bool = True
    no_raw_intermediate_json: bool = True
    verified_facts_preferred: bool = True


@dataclass
class PrimaryRuntimeRequestEnvelope:
    """Canonical auxiliary_brain -> ai_core request envelope."""

    request_type: Literal["agent_execution", "final_synthesis", "rerun", "missing_information"]
    task_name: str
    participant_name: str = ""
    participant_id: str = ""
    objective: str = ""
    task_instruction: str = ""
    community_id: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    execution_policy: PrimaryRuntimeExecutionPolicy = field(default_factory=PrimaryRuntimeExecutionPolicy)
    expected_output: dict[str, Any] = field(default_factory=lambda: {
        "type": "final_user_answer",
        "no_raw_json": True,
        "verified_facts_only_when_available": True,
    })

    def to_prompt_payload(self) -> dict[str, Any]:
        return {
            "request_type": self.request_type,
            "task_name": self.task_name,
            "participant_name": self.participant_name,
            "participant_id": self.participant_id,
            "objective": self.objective,
            "task_instruction": self.task_instruction,
            "community_id": self.community_id,
            "context": self.context,
            "execution_policy": self.execution_policy.__dict__,
            "expected_output": self.expected_output,
        }
