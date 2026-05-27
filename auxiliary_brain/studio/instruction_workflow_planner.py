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
        aliases: dict[str, str] = {}

        if semantic_steps:
            for step in semantic_steps:
                step_id = str(step.get("id") or f"semantic_step_{len(tasks) + 1}").strip()
                if step.get("executable") is False:
                    aliases[step_id] = ""
                    covered.append({"step_id": step_id, "type": "non_executable_metadata"})
                    continue
                route = step.get("route") if isinstance(step.get("route"), dict) else {}
                route_ref = str(route.get("participant_id") or route.get("participant_name") or step.get("participant_id") or "").strip()
                participant = self._find_participant(route_ref, candidates) if route_ref else None
                depends_on = [aliases.get(str(dep), str(dep)) for dep in (step.get("depends_on") or []) if str(dep).strip() and aliases.get(str(dep), str(dep))]
                if participant:
                    pid = self._participant_id(participant)
                    if not pid:
                        uncovered.append({"step_id": step_id, "reason": "participant_without_id"})
                        continue
                    selected_by_graph.append(participant)
                    aliases[step_id] = pid
                    tasks.append({
                        "task_id": f"{graph_id}_delegate_{len(tasks) + 1}",
                        "participant_id": pid,
                        "participant_display_name": self._participant_name(participant),
                        "execution_owner": "ai_core",
                        "status": "pending",
                        "step_type": "participant_execution",
                        "depends_on": depends_on,
                        "source_step_id": step_id,
                        "source_instruction_fragment": step.get("instruction_fragment") or "",
                        **self._task_contracts_from_step(step, depends_on),
                    })
                    covered.append({"step_id": step_id, "type": "participant_execution", "participant_id": pid})
                    continue

                virtual_id = new_id_fn("participant")
                aliases[step_id] = virtual_id
                objective = self._objective_from_step(step)
                virtual = {
                    "participant_id": virtual_id,
                    "name": step.get("label") or f"Generated Step {len(generated) + 1}",
                    "agent_name": step.get("label") or f"Generated Step {len(generated) + 1}",
                    "display_name": step.get("label") or f"Generated Step {len(generated) + 1}",
                    "role_name": step.get("label") or f"Generated Step {len(generated) + 1}",
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
                    "generated_by": "semantic_workflow_planning",
                    "depends_on": depends_on,
                    "input_from": depends_on,
                    "workflow_step_type": "semantic_intermediate_step",
                    "source_step_id": step_id,
                }
                generated.append(virtual)
                tasks.append({
                    "task_id": f"{graph_id}_delegate_{len(tasks) + 1}",
                    "participant_id": virtual_id,
                    "participant_display_name": virtual.get("display_name") or virtual.get("name"),
                    "execution_owner": "ai_core",
                    "status": "pending",
                    "step_type": "semantic_intermediate_step",
                    "depends_on": depends_on,
                    "input_from": depends_on,
                    "source_step_id": step_id,
                    "source_instruction_fragment": step.get("instruction_fragment") or "",
                    **self._task_contracts_from_step(step, depends_on),
                })
                covered.append({"step_id": step_id, "type": "semantic_intermediate_step", "participant_id": virtual_id})
        else:
            # No semantic graph was supplied.  Use a domain-neutral structural
            # fallback that only relies on declared participant names and generic
            # sequencing configuration.  This prevents downstream dataflow
            # fragments from being silently dropped when a semantic provider is
            # unavailable.
            structural_steps = StructuralStepPlanner().build_steps(str(instruction or ""), candidates)
            if structural_steps:
                for step in structural_steps:
                    step_id = str(step.get("id") or f"structural_step_{len(tasks) + 1}").strip()
                    route = step.get("route") if isinstance(step.get("route"), dict) else {}
                    route_ref = str(route.get("participant_id") or route.get("participant_name") or step.get("participant_id") or "").strip()
                    participant = self._find_participant(route_ref, candidates) if route_ref else None
                    depends_on = [str(dep).strip() for dep in (step.get("depends_on") or []) if str(dep).strip()]
                    if participant:
                        pid = self._participant_id(participant)
                        if not pid:
                            uncovered.append({"step_id": step_id, "reason": "participant_without_id"})
                            continue
                        selected_by_graph.append(participant)
                        tasks.append({
                            "task_id": f"{graph_id}_delegate_{len(tasks) + 1}",
                            "participant_id": pid,
                            "participant_display_name": self._participant_name(participant),
                            "execution_owner": "ai_core",
                            "status": "pending",
                            "step_type": "participant_execution",
                            "depends_on": depends_on,
                            "source_step_id": step_id,
                            "source_instruction_fragment": step.get("instruction_fragment") or "",
                            **self._task_contracts_from_step(step, depends_on),
                        })
                        covered.append({"step_id": step_id, "type": "participant_execution", "participant_id": pid})
                        continue

                    virtual_id = new_id_fn("participant")
                    objective = self._objective_from_step(step)
                    virtual = {
                        "participant_id": virtual_id,
                        "name": step.get("label") or f"Generated Step {len(generated) + 1}",
                        "agent_name": step.get("label") or f"Generated Step {len(generated) + 1}",
                        "display_name": step.get("label") or f"Generated Step {len(generated) + 1}",
                        "role_name": step.get("label") or f"Generated Step {len(generated) + 1}",
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
                        "generated_by": "structural_workflow_planning",
                        "depends_on": depends_on,
                        "input_from": depends_on,
                        "workflow_step_type": "semantic_intermediate_step",
                        "source_step_id": step_id,
                    }
                    generated.append(virtual)
                    tasks.append({
                        "task_id": f"{graph_id}_delegate_{len(tasks) + 1}",
                        "participant_id": virtual_id,
                        "participant_display_name": virtual.get("display_name") or virtual.get("name"),
                        "execution_owner": "ai_core",
                        "status": "pending",
                        "step_type": "semantic_intermediate_step",
                        "depends_on": depends_on,
                        "input_from": depends_on,
                        "source_step_id": step_id,
                        "source_instruction_fragment": step.get("instruction_fragment") or "",
                        **self._task_contracts_from_step(step, depends_on),
                    })
                    covered.append({"step_id": step_id, "type": "semantic_intermediate_step", "participant_id": virtual_id})
            else:
                matched = self._match_participants_by_declared_names(str(instruction or ""), candidates)
                if not matched and candidates:
                    matched = self._dedupe(candidates)
                    covered.append({"type": "implicit_participant_selection", "participant_count": len(matched)})
                for participant in matched:
                    pid = self._participant_id(participant)
                    if not pid:
                        continue
                    selected_by_graph.append(participant)
                    tasks.append({
                        "task_id": f"{graph_id}_delegate_{len(tasks) + 1}",
                        "participant_id": pid,
                        "participant_display_name": self._participant_name(participant),
                        "execution_owner": "ai_core",
                        "status": "pending",
                        "step_type": "participant_execution",
                        "depends_on": [],
                        "source_instruction_fragment": self._participant_name(participant),
                        "input_contract": {
                            "contract_type": "runtime_step_input_contract",
                            "bound_from_upstream": [],
                            "accepts_verified_material": False,
                            "user_input_required_for_bound_material": False,
                        },
                        "output_contract": {
                            "contract_type": "runtime_step_output_contract",
                            "produces_verified_material": True,
                            "planner_metadata_is_not_result_material": True,
                        },
                    })
                    covered.append({"type": "participant_execution", "participant_id": pid, "participant_name": self._participant_name(participant)})

        selected = self._dedupe(selected_by_graph + generated)
        expected_count = len(semantic_steps) if semantic_steps else len(tasks)
        coverage = {
            "status": "passed" if not uncovered and len(tasks) >= expected_count else "incomplete",
            "covered_actions": covered,
            "uncovered_fragments": uncovered,
            "selected_participant_count": len(selected_by_graph),
            "generated_step_count": len(generated),
            "planning_mode": "semantic_graph_mapping" if semantic_steps else ("structural_graph_mapping" if tasks and any((t.get("depends_on") or []) for t in tasks) else "structural_participant_mapping"),
            "semantic_step_count": len(semantic_steps),
        }
        return PlannedWorkflow(selected_participants=selected, generated_participants=generated, tasks=tasks, coverage=coverage)


    def _task_contracts_from_step(self, step: dict[str, Any], depends_on: list[str]) -> dict[str, Any]:
        input_contract = step.get("input_contract") if isinstance(step.get("input_contract"), dict) else {}
        output_contract = step.get("output_contract") if isinstance(step.get("output_contract"), dict) else {}
        if not input_contract:
            input_contract = {
                "contract_type": "runtime_step_input_contract",
                "bound_from_upstream": [str(x) for x in depends_on or [] if str(x)],
                "accepts_verified_material": bool(depends_on),
                "user_input_required_for_bound_material": False,
            }
        if not output_contract:
            output_contract = {
                "contract_type": "runtime_step_output_contract",
                "produces_verified_material": True,
                "planner_metadata_is_not_result_material": True,
            }
        return {"input_contract": input_contract, "output_contract": output_contract}

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
