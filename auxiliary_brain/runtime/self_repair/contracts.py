from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

RepairLevel = Literal[
    "deterministic",
    "runtime_knowledge",
    "web_evidence",
    "human_escalation",
]


@dataclass
class FailureReport:
    """Generic failure envelope used by the runtime self-repair engine.

    The report is intentionally domain-neutral. It can describe schema,
    parameter, binding, state, execution, verification, or presentation failures
    without encoding any task-specific vocabulary in ai_core.
    """

    run_id: str = ""
    node_id: str = ""
    stage: str = ""
    status: str = "failed"
    message: str = ""
    error_type: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    expected_contract: dict[str, Any] = field(default_factory=dict)
    actual_material: dict[str, Any] = field(default_factory=dict)
    runtime_state: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RepairAction:
    action_type: str
    level: RepairLevel
    description: str
    target_path: str = ""
    before: Any = None
    after: Any = None
    safe_to_apply: bool = False
    requires_validation: bool = True
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RepairPlan:
    status: str
    classification: str
    actions: list[RepairAction] = field(default_factory=list)
    requires_web_evidence: bool = False
    requires_human_review: bool = False
    reason: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def can_auto_apply(self) -> bool:
        return bool(self.actions) and all(a.safe_to_apply for a in self.actions) and not self.requires_human_review

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["can_auto_apply"] = self.can_auto_apply
        return data


@dataclass
class RepairResult:
    status: str
    applied: bool
    repaired_payload: dict[str, Any] = field(default_factory=dict)
    plan: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
