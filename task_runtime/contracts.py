from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class TaskRuntimeRevision:
    task_name: str
    task_revision: int
    graph_revision: int
    plan_revision: int
    active_revision_id: str
    source_instruction_fingerprint: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
