from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


@dataclass
class PlannedWorkflow:
    selected_participants: list[dict[str, Any]]
    generated_participants: list[dict[str, Any]]
    tasks: list[dict[str, Any]]
    coverage: dict[str, Any]


class InstructionWorkflowPlanner:
    """Build a generic executable task graph from a user instruction.

    The planner is intentionally domain-neutral.  It does not know what a
    participant does.  It only uses explicit participant names/ids, command
    structure, generic dependency markers, and generic transformation verbs.
    """

    TRANSFORM_VERBS = (
        "translate", "summarize", "summary", "format", "convert", "rewrite",
        "extract", "compare", "classify", "analyze", "validate", "verify",
        "整理", "翻译", "翻訳", "要約", "总结", "変換", "转换", "比較", "分析",
    )
    DEPENDENCY_MARKERS = (
        "answer", "result", "output", "response", "previous", "upstream",
        "结果", "答案", "回答", "出力", "結果", "前の",
    )

    def plan(self, *, instruction: str, participants: list[dict[str, Any]], graph_id: str, new_id_fn) -> PlannedWorkflow:
        text = str(instruction or "").strip()
        candidates = [p for p in participants if isinstance(p, dict)]
        matched = self._match_participants(text, candidates)
        generated: list[dict[str, Any]] = []
        tasks: list[dict[str, Any]] = []
        covered: list[dict[str, Any]] = []
        uncovered: list[str] = []

        if not matched and candidates:
            # Preserve existing permissive behavior: when no participant is
            # named, let the task graph include all current participants.  This
            # is still domain-neutral and keeps legacy multi-agent tasks working.
            matched = self._dedupe(candidates)
            covered.append({"type": "implicit_participant_selection", "participant_count": len(matched)})

        for index, participant in enumerate(matched):
            pid = self._participant_id(participant)
            if not pid:
                continue
            tasks.append({
                "task_id": f"{graph_id}_delegate_{len(tasks) + 1}",
                "participant_id": pid,
                "execution_owner": "ai_core",
                "status": "pending",
                "step_type": "participant_execution",
                "depends_on": [],
                "source_instruction_fragment": self._participant_name(participant),
            })
            covered.append({"type": "participant_execution", "participant_id": pid, "participant_name": self._participant_name(participant)})

        transform_fragments = self._extract_transform_fragments(text, matched)
        for fragment in transform_fragments:
            upstream = self._resolve_upstream_for_fragment(fragment, matched)
            if not upstream and matched:
                upstream = matched[-1]
            if not upstream:
                uncovered.append(fragment)
                continue
            upstream_id = self._participant_id(upstream)
            virtual_id = new_id_fn("participant")
            virtual_name = f"Generated Step {len(generated) + 1}"
            objective = self._build_transform_objective(fragment, upstream)
            virtual_participant = {
                "participant_id": virtual_id,
                "name": virtual_name,
                "agent_name": virtual_name,
                "display_name": virtual_name,
                "role_name": virtual_name,
                "instruction": objective,
                "execution_objective": objective,
                "definition_instruction": fragment,
                "parameter_contract": {
                    "contract_type": "generated_intermediate_step_contract",
                    "parameters": [],
                    "missing_information": [],
                    "runtime_scope": "task_run",
                },
                "runtime_parameters": {},
                "missing_information": [],
                "origin": "auxiliary_brain",
                "status": "created",
                "execution_policy": "delegate_to_ai_core",
                "generated_by": "instruction_workflow_planning",
                "depends_on": [upstream_id],
                "input_from": [upstream_id],
                "workflow_step_type": "result_transform",
            }
            generated.append(virtual_participant)
            tasks.append({
                "task_id": f"{graph_id}_delegate_{len(tasks) + 1}",
                "participant_id": virtual_id,
                "execution_owner": "ai_core",
                "status": "pending",
                "step_type": "result_transform",
                "depends_on": [upstream_id],
                "input_from": [upstream_id],
                "source_instruction_fragment": fragment,
            })
            covered.append({
                "type": "result_transform",
                "participant_id": virtual_id,
                "depends_on": [upstream_id],
                "fragment": fragment,
            })

        selected = self._dedupe(matched + generated)
        coverage = {
            "status": "passed" if not uncovered else "incomplete",
            "covered_actions": covered,
            "uncovered_fragments": uncovered,
            "selected_participant_count": len(matched),
            "generated_step_count": len(generated),
            "planning_mode": "generic_instruction_decomposition",
        }
        return PlannedWorkflow(selected_participants=selected, generated_participants=generated, tasks=tasks, coverage=coverage)

    def _match_participants(self, text: str, participants: list[dict[str, Any]]) -> list[dict[str, Any]]:
        lowered = text.casefold()
        selected: list[dict[str, Any]] = []
        # Prefer longer names so "Agent A" is not swallowed by "Agent".
        ordered = sorted(participants, key=lambda p: len(self._participant_name(p)), reverse=True)
        for participant in ordered:
            name = self._participant_name(participant)
            pid = self._participant_id(participant)
            aliases = [name, pid]
            for alias in aliases:
                alias_clean = str(alias or "").strip()
                if not alias_clean:
                    continue
                if alias_clean.casefold() in lowered:
                    selected.append(participant)
                    break
        return self._dedupe(selected)

    def _extract_transform_fragments(self, text: str, matched: list[dict[str, Any]]) -> list[str]:
        fragments: list[str] = []
        normalized = " ".join(str(text or "").split())
        if not normalized:
            return fragments
        for verb in self.TRANSFORM_VERBS:
            pattern = re.compile(rf"\b{re.escape(verb)}\b.+", flags=re.IGNORECASE) if re.match(r"^[A-Za-z]+$", verb) else re.compile(re.escape(verb) + r".+", flags=re.IGNORECASE)
            match = pattern.search(normalized)
            if match:
                fragment = match.group(0).strip(" .。")
                if self._looks_like_dependent_transform(fragment):
                    fragments.append(fragment)
        # In case several verbs match the same tail, keep the shortest distinct
        # fragment first and remove contained duplicates.
        fragments = sorted(set(fragments), key=len)
        result: list[str] = []
        for fragment in fragments:
            if not any(fragment in existing or existing in fragment for existing in result):
                result.append(fragment)
        return result

    def _looks_like_dependent_transform(self, fragment: str) -> bool:
        lowered = fragment.casefold()
        has_marker = any(marker.casefold() in lowered for marker in self.DEPENDENCY_MARKERS)
        # A transform may also be dependent when it explicitly says it uses an
        # upstream participant name; this is checked later.  Keep the marker rule
        # conservative to avoid turning unrelated commands into dependencies.
        return has_marker

    def _resolve_upstream_for_fragment(self, fragment: str, matched: list[dict[str, Any]]) -> dict[str, Any] | None:
        lowered = fragment.casefold()
        for participant in sorted(matched, key=lambda p: len(self._participant_name(p)), reverse=True):
            name = self._participant_name(participant).casefold()
            pid = self._participant_id(participant).casefold()
            if (name and name in lowered) or (pid and pid in lowered):
                return participant
        return None

    def _build_transform_objective(self, fragment: str, upstream: dict[str, Any]) -> str:
        upstream_name = self._participant_name(upstream)
        return (
            "Use only the declared upstream result from "
            f"{upstream_name}. Apply this requested transformation to that result: "
            f"{str(fragment).strip()}"
        )

    def _dedupe(self, participants: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for participant in participants:
            pid = self._participant_id(participant)
            key = pid or self._participant_name(participant).casefold()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(participant)
        return out

    def _participant_id(self, participant: dict[str, Any]) -> str:
        return str(participant.get("participant_id") or participant.get("id") or participant.get("name") or "").strip()

    def _participant_name(self, participant: dict[str, Any]) -> str:
        return str(participant.get("display_name") or participant.get("agent_name") or participant.get("name") or participant.get("participant_id") or participant.get("id") or "").strip()
