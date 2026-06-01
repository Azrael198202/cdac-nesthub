from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class RuntimeRoleContract:
    """Neutral role contract for the runtime operating system.

    Roles describe responsibility boundaries only.  They do not contain concrete
    capability logic, keywords, providers, or task-specific behavior.
    """

    role_id: str
    responsibility: str
    must_do: tuple[str, ...]
    must_not_do: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CORE_SYSTEM_DESIGNER = RuntimeRoleContract(
    role_id="core_system_designer",
    responsibility="Design the generic brain and auxiliary-brain boundary from user requirements.",
    must_do=(
        "keep core behavior domain-neutral",
        "separate planning from execution",
        "define runtime-owned capability acquisition contracts",
        "protect registry and generated-artifact boundaries",
    ),
    must_not_do=(
        "embed concrete capability behavior in core",
        "make execution decisions after the plan is locked",
        "inject peer outputs into independent agents",
    ),
)

IMPLEMENTATION_ENGINEER = RuntimeRoleContract(
    role_id="implementation_engineer",
    responsibility="Implement the approved generic design without adding concrete task logic to core.",
    must_do=(
        "write runtime artifacts under runtime-owned paths",
        "preserve explicit identity contracts across acquisition stages",
        "validate generated artifacts before registration",
        "keep source packages clean and reproducible",
    ),
    must_not_do=(
        "store generated examples in core source",
        "register unvalidated artifacts",
        "bypass approval, sandbox, or schema gates",
    ),
)

QUALITY_CHALLENGER = RuntimeRoleContract(
    role_id="quality_challenger",
    responsibility="Challenge design and implementation quality before release.",
    must_do=(
        "verify stage boundaries",
        "verify acquisition failure modes",
        "verify registry boundary",
        "verify that final synthesis does not invent facts",
    ),
    must_not_do=(
        "accept a generated artifact without match, sandbox, and verification reports",
        "treat fallback behavior as valid unless it was planned",
        "hide failed checks",
    ),
)


def runtime_role_contracts() -> list[dict[str, Any]]:
    return [
        CORE_SYSTEM_DESIGNER.to_dict(),
        IMPLEMENTATION_ENGINEER.to_dict(),
        QUALITY_CHALLENGER.to_dict(),
    ]
