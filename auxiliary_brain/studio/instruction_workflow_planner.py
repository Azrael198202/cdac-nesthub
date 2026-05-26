from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from auxiliary_brain.studio.structural_step_planner import StructuralStepPlanner


@dataclass
class PlannedWorkflow:
    selected_participants: list[dict[str, Any]]
    generated_participants: list[dict[str, Any]]
    tasks: list[dict[str, Any]]
    coverage: dict[str, Any]


class InstructionWorkflowPlanner:
    """Build a task graph from a runtime semantic plan.

    This class is deliberately vocabulary-free.  It does not contain operation
    words, domain words, language words, or dependency marker dictionaries.
    It only knows how to map a normalized semantic graph into an executable
    graph.  The semantic graph must be produced by the runtime planner/LLM or
    by a runtime-generated adapter outside ai_core/source code.
    """

    def plan(
        self,
        *,
        instruction: str,
        participants: list[dict[str, Any]],
        graph_id: str,
        new_id_fn,
        semantic_plan: dict[str, Any] | None = None,
    ) -> PlannedWorkflow:
        candidates = [p for p in participants if isinstance(p, dict)]
        semantic_plan = semantic_plan if isinstance(semantic_plan, dict) else {}
        semantic_steps = self._semantic_steps(semantic_plan)
        selected_by_graph: list[dict[str, Any]] = []
        generated: list[dict[str, Any]] = []
        tasks: list[dict[str, Any]] = []
        covered: list[dict[str, Any]] = []
        uncovered: list[dict[str, Any]] = []
        graph_aliases: dict[str, str] = {}
        participant_aliases: dict[str, str] = {}

        def add_generated_step(step: dict[str, Any], step_id: str, runtime_depends_on: list[str], graph_depends_on: list[str], generated_by: str) -> None:
            virtual_id = new_id_fn("participant")
            task_id = self._task_id_for_index(graph_id, len(tasks) + 1)
            graph_aliases[step_id] = task_id
            participant_aliases[step_id] = virtual_id
            objective = self._objective_from_step(step)
            label = step.get("label") or self._label_from_objective(objective) or f"Generated Step {len(generated) + 1}"
            virtual = {
                "participant_id": virtual_id,
                "name": label,
                "agent_name": label,
                "display_name": label,
                "role_name": label,
                "instruction": objective,
                "execution_objective": objective,
                "definition_instruction": step.get("instruction_fragment") or objective,
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
                "generated_by": generated_by,
                "depends_on": runtime_depends_on,
                "input_from": runtime_depends_on,
                "workflow_step_type": "semantic_intermediate_step",
                "source_step_id": step_id,
                "workflow_node_id": task_id,
            }
            generated.append(virtual)
            tasks.append({
                "task_id": task_id,
                "node_id": task_id,
                "participant_id": virtual_id,
                "executor_ref": virtual_id,
                "execution_owner": "ai_core",
                "status": "pending",
                "step_type": "semantic_intermediate_step",
                "depends_on": runtime_depends_on,
                "input_from": runtime_depends_on,
                "graph_depends_on": graph_depends_on,
                "source_step_id": step_id,
                "source_instruction_fragment": step.get("instruction_fragment") or objective,
                "label": label,
            })
            covered.append({"step_id": step_id, "type": "semantic_intermediate_step", "participant_id": virtual_id, "task_id": task_id})

        def add_participant_step(step: dict[str, Any], step_id: str, participant: dict[str, Any], runtime_depends_on: list[str], graph_depends_on: list[str]) -> None:
            pid = self._participant_id(participant)
            if not pid:
                uncovered.append({"step_id": step_id, "reason": "participant_without_id"})
                return
            selected_by_graph.append(participant)
            task_id = self._task_id_for_index(graph_id, len(tasks) + 1)
            graph_aliases[step_id] = task_id
            participant_aliases[step_id] = pid
            label = self._participant_name(participant) or step.get("label") or task_id
            tasks.append({
                "task_id": task_id,
                "node_id": task_id,
                "participant_id": pid,
                "executor_ref": pid,
                "execution_owner": "ai_core",
                "status": "pending",
                "step_type": "participant_execution",
                "depends_on": runtime_depends_on,
                "graph_depends_on": graph_depends_on,
                "source_step_id": step_id,
                "source_instruction_fragment": step.get("instruction_fragment") or label,
                "label": label,
            })
            covered.append({"step_id": step_id, "type": "participant_execution", "participant_id": pid, "task_id": task_id})

        steps_for_mapping: list[dict[str, Any]] = []
        mapping_mode = ""
        if semantic_steps:
            steps_for_mapping = semantic_steps
            mapping_mode = "semantic_graph_mapping"
        else:
            structural_steps = StructuralStepPlanner().build_steps(str(instruction or ""), candidates)
            if structural_steps:
                steps_for_mapping = structural_steps
                mapping_mode = "structural_graph_mapping"

        if steps_for_mapping:
            for step in steps_for_mapping:
                step_id = str(step.get("id") or f"workflow_step_{len(tasks) + 1}").strip()
                if step.get("executable") is False:
                    graph_aliases[step_id] = ""
                    participant_aliases[step_id] = ""
                    covered.append({"step_id": step_id, "type": "non_executable_metadata"})
                    continue
                graph_depends_on = [graph_aliases.get(str(dep), str(dep)) for dep in (step.get("depends_on") or []) if str(dep).strip() and graph_aliases.get(str(dep), str(dep))]
                runtime_depends_on = [participant_aliases.get(str(dep), str(dep)) for dep in (step.get("depends_on") or []) if str(dep).strip() and participant_aliases.get(str(dep), str(dep))]
                route = step.get("route") if isinstance(step.get("route"), dict) else {}
                route_ref = str(route.get("participant_id") or route.get("participant_name") or step.get("participant_id") or "").strip()
                participant = self._find_participant(route_ref, candidates) if route_ref else None
                if participant and not self._participant_is_explicit_for_step(participant, step):
                    participant = None
                if participant:
                    add_participant_step(step, step_id, participant, runtime_depends_on, graph_depends_on)
                else:
                    add_generated_step(step, step_id, runtime_depends_on, graph_depends_on, "semantic_workflow_planning" if semantic_steps else "structural_workflow_planning")
        else:
            matched = self._match_participants_by_declared_names(str(instruction or ""), candidates)
            if not matched and candidates:
                matched = self._dedupe(candidates)
                covered.append({"type": "implicit_participant_selection", "participant_count": len(matched)})
            for participant in matched:
                pid = self._participant_id(participant)
                if not pid:
                    continue
                step = {"id": f"participant_step_{len(tasks) + 1}", "label": self._participant_name(participant), "instruction_fragment": self._participant_name(participant)}
                add_participant_step(step, str(step["id"]), participant, [], [])
            mapping_mode = "structural_participant_mapping"

        selected = self._dedupe(selected_by_graph + generated)
        expected_count = len(semantic_steps) if semantic_steps else len(tasks)
        coverage = {
            "status": "passed" if not uncovered and len(tasks) >= expected_count else "incomplete",
            "covered_actions": covered,
            "uncovered_fragments": uncovered,
            "selected_participant_count": len(selected_by_graph),
            "generated_step_count": len(generated),
            "planning_mode": mapping_mode,
            "semantic_step_count": len(semantic_steps),
        }
        return PlannedWorkflow(selected_participants=selected, generated_participants=generated, tasks=tasks, coverage=coverage)

    def _semantic_steps(self, semantic_plan: dict[str, Any]) -> list[dict[str, Any]]:
        steps = semantic_plan.get("steps") or semantic_plan.get("actions") or []
        return [s for s in steps if isinstance(s, dict)] if isinstance(steps, list) else []

    def _objective_from_step(self, step: dict[str, Any]) -> str:
        parts = []
        seen_values: set[str] = set()
        for field in ("objective", "instruction", "instruction_fragment", "description"):
            value = step.get(field)
            if value not in (None, ""):
                normalized = " ".join(str(value).split())
                if normalized and normalized not in seen_values:
                    seen_values.add(normalized)
                    parts.append(str(value))
        if not parts:
            parts.append("Complete the normalized workflow step using declared upstream inputs and return only the step result.")
        return "\n".join(parts)



    def _label_from_objective(self, objective: Any) -> str:
        text = " ".join(str(objective or "").split())
        if not text:
            return ""
        return text[:80]

    def _participant_is_explicit_for_step(self, participant: dict[str, Any], step: dict[str, Any]) -> bool:
        """Return True only when a routed participant is explicitly named by the step.

        The semantic planner may occasionally route a post-processing step to an
        unrelated reusable participant.  A workflow step should use a reusable
        participant only when the step text explicitly references that
        participant identity.  Otherwise the step remains a generated workflow
        node.  This keeps participant profiles from becoming workflow nodes and
        prevents unrelated parameter contracts from leaking into generated
        dataflow steps.
        """
        haystack = " ".join(
            str(step.get(field) or "")
            for field in ("instruction_fragment", "instruction", "objective", "description", "label")
        ).casefold()
        if not haystack:
            return False
        aliases = [self._participant_name(participant), self._participant_id(participant)]
        return any(str(alias or "").strip().casefold() in haystack for alias in aliases if str(alias or "").strip())

    def _task_id_for_index(self, graph_id: str, index: int) -> str:
        return f"{graph_id}_delegate_{index}"

    def _find_participant(self, ref: str, participants: list[dict[str, Any]]) -> dict[str, Any] | None:
        ref_clean = str(ref or "").strip().casefold()
        if not ref_clean:
            return None
        for participant in participants:
            values = {self._participant_id(participant).casefold(), self._participant_name(participant).casefold()}
            if ref_clean in values:
                return participant
        return None

    def _match_participants_by_declared_names(self, text: str, participants: list[dict[str, Any]]) -> list[dict[str, Any]]:
        lowered = str(text or "").casefold()
        selected: list[dict[str, Any]] = []
        for participant in sorted(participants, key=lambda p: len(self._participant_name(p)), reverse=True):
            for alias in (self._participant_name(participant), self._participant_id(participant)):
                alias_clean = str(alias or "").strip()
                if alias_clean and alias_clean.casefold() in lowered:
                    selected.append(participant)
                    break
        return self._dedupe(selected)

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
