from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from auxiliary_brain.studio.structural_step_planner import StructuralStepPlanner


@dataclass(frozen=True)
class SemanticGraphVerificationResult:
    status: str
    issues: list[dict[str, Any]]
    repaired_plan: dict[str, Any]
    structural_steps: list[dict[str, Any]]
    declared_step_count: int
    semantic_step_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "issues": self.issues,
            "declared_step_count": self.declared_step_count,
            "semantic_step_count": self.semantic_step_count,
            "structural_step_count": len(self.structural_steps),
            "repair_applied": self.repaired_plan.get("repair_applied") is True,
            "repair_strategy": self.repaired_plan.get("repair_strategy"),
        }


class SemanticTaskGraphVerifier:
    """Checks that a semantic task graph preserves the user's declared work.

    This layer is intentionally domain-neutral.  It does not know any
    business vocabulary.  It only verifies structural coverage:
    - explicit numbered/requested fragments are not silently dropped;
    - declared participants referenced by the instruction remain executable;
    - generated downstream fragments that depend on earlier outputs are kept;
    - malformed/under-covered semantic JSON is replaced by the structural
      fallback graph before compile/execution.
    """

    def __init__(self, structural_planner: StructuralStepPlanner | None = None) -> None:
        self.structural_planner = structural_planner or StructuralStepPlanner()

    def verify_and_repair(
        self,
        *,
        instruction: str,
        participants: list[dict[str, Any]],
        semantic_plan: dict[str, Any] | None,
    ) -> SemanticGraphVerificationResult:
        plan = semantic_plan if isinstance(semantic_plan, dict) else {"steps": []}
        semantic_steps = [s for s in plan.get("steps", []) if isinstance(s, dict)] if isinstance(plan.get("steps"), list) else []
        executable_semantic_steps = [s for s in semantic_steps if s.get("executable") is not False]
        structural_steps = self.structural_planner.build_steps(str(instruction or ""), participants)
        declared_step_count = self._declared_step_count(structural_steps)
        executable_structural_steps = [s for s in structural_steps if isinstance(s, dict) and s.get("executable") is not False]
        issues: list[dict[str, Any]] = []

        if declared_step_count and len(executable_semantic_steps) < len(executable_structural_steps):
            issues.append({
                "code": "semantic_graph_lost_declared_steps",
                "expected_min_executable_steps": len(executable_structural_steps),
                "actual_executable_steps": len(executable_semantic_steps),
            })

        missing_participants = self._missing_declared_participants(executable_semantic_steps, executable_structural_steps, participants)
        if missing_participants:
            issues.append({
                "code": "semantic_graph_lost_declared_participants",
                "missing_participant_ids": missing_participants,
            })

        missing_declared_ids = self._missing_declared_step_ids(executable_semantic_steps, executable_structural_steps)
        if missing_declared_ids:
            issues.append({
                "code": "semantic_graph_lost_declared_step_ids",
                "missing_declared_step_ids": missing_declared_ids,
            })

        repaired = dict(plan)
        if issues and executable_structural_steps:
            repaired = {
                "steps": executable_structural_steps,
                "coverage_notes": list(plan.get("coverage_notes") or []) + ["semantic_graph_verification_repaired_by_structural_fallback"],
                "verification": {
                    "status": "repaired",
                    "issues": issues,
                    "repair_strategy": "replace_undercovered_semantic_graph_with_structural_graph",
                },
                "repair_applied": True,
                "repair_strategy": "structural_fallback",
            }
        else:
            notes = list(plan.get("coverage_notes") or [])
            if "semantic_graph_verification_passed" not in notes:
                notes.append("semantic_graph_verification_passed")
            repaired = dict(plan)
            repaired["coverage_notes"] = notes
            repaired["verification"] = {"status": "passed", "issues": []}

        return SemanticGraphVerificationResult(
            status="repaired" if issues and executable_structural_steps else ("failed" if issues else "passed"),
            issues=issues,
            repaired_plan=repaired,
            structural_steps=executable_structural_steps,
            declared_step_count=declared_step_count,
            semantic_step_count=len(executable_semantic_steps),
        )

    def _declared_step_count(self, structural_steps: list[dict[str, Any]]) -> int:
        ids = {str(s.get("declared_step_id") or "").strip().casefold() for s in structural_steps if isinstance(s, dict) and str(s.get("declared_step_id") or "").strip()}
        return len(ids)

    def _missing_declared_participants(self, semantic_steps: list[dict[str, Any]], structural_steps: list[dict[str, Any]], participants: list[dict[str, Any]]) -> list[str]:
        semantic_ids = set()
        for step in semantic_steps:
            route = step.get("route") if isinstance(step.get("route"), dict) else {}
            ref = str(route.get("participant_id") or route.get("participant_name") or step.get("participant_id") or "").strip()
            if ref:
                semantic_ids.add(ref)
        aliases = self._participant_aliases(participants)
        semantic_ids = {aliases.get(item.casefold(), item) for item in semantic_ids}
        structural_ids = set()
        for step in structural_steps:
            route = step.get("route") if isinstance(step.get("route"), dict) else {}
            ref = str(route.get("participant_id") or step.get("participant_id") or "").strip()
            if ref:
                structural_ids.add(ref)
        return sorted(structural_ids - semantic_ids)

    def _missing_declared_step_ids(self, semantic_steps: list[dict[str, Any]], structural_steps: list[dict[str, Any]]) -> list[str]:
        semantic_declared = {str(s.get("declared_step_id") or s.get("id") or "").strip().casefold() for s in semantic_steps if str(s.get("declared_step_id") or s.get("id") or "").strip()}
        missing: list[str] = []
        for step in structural_steps:
            declared = str(step.get("declared_step_id") or "").strip()
            if declared and declared.casefold() not in semantic_declared:
                missing.append(declared)
        return sorted(set(missing))


    def _participant_aliases(self, participants: list[dict[str, Any]]) -> dict[str, str]:
        aliases: dict[str, str] = {}
        for participant in participants or []:
            if not isinstance(participant, dict):
                continue
            pid = str(participant.get("participant_id") or participant.get("id") or participant.get("name") or "").strip()
            if not pid:
                continue
            for key in ("participant_id", "id", "name", "agent_name", "display_name", "role_name"):
                value = str(participant.get(key) or "").strip()
                if value:
                    aliases[value.casefold()] = pid
        return aliases
