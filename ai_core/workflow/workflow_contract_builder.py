from __future__ import annotations

from typing import Any

from ai_core.workflow.execution_options import (
    ACTION_CONTRACTS,
    ACTION_TO_METHOD,
    AGENT_ACTION_PROMPT_CONTRACT,
    SELECTION_RULES,
    fixed_options_for_prompt,
    is_fixed_action,
    method_for_action,
    normalize_action_type,
)
from ai_core.artifacts.artifact_registry import UploadedArtifactRegistry


class WorkflowContractBuilder:
    """Domain-neutral workflow output normalizer.

    It guarantees that workflow_planning produces a locked execution_plan with
    planned_steps, agent_graph, ranked execution options, and source policy.
    It never decides business semantics; it only uses upstream structured
    intent/context and fixed runtime action options.
    """

    def __init__(self) -> None:
        self.artifact_registry = UploadedArtifactRegistry()

    def fixed_action_types(self) -> list[str]:
        return list(ACTION_TO_METHOD.keys())

    def normalize_workflow_result(self, *, result: dict[str, Any], state: dict[str, Any], slim_user_input: str = "") -> dict[str, Any]:
        if not isinstance(result, dict):
            result = {}
        # v5.4: planner output can be nested by adapters/wrappers. Always
        # search the whole generic record for the first valid execution
        # decision and the deepest valid planned_steps before falling back.
        decision = self.extract_execution_decision(result)
        artifact_decision = self.artifact_forced_decision(state, slim_user_input)
        if artifact_decision.get("selected_action_type"):
            decision = artifact_decision
        if not decision.get("selected_action_type"):
            decision = self.default_execution_decision(state=state, result=result)
        steps = self.extract_planned_steps(result)
        if not steps:
            steps = [self.default_step(state=state, result=result, decision=decision, slim_user_input=slim_user_input)]
        execution_instruction = self.extract_execution_instruction(result)
        normalized_steps = [
            self.normalize_step(
                step=step,
                index=index,
                state=state,
                decision=decision,
                execution_instruction=execution_instruction,
            )
            for index, step in enumerate(steps)
            if isinstance(step, dict)
        ]
        if not normalized_steps:
            normalized_steps = [
                self.normalize_step(
                    step=self.default_step(state=state, result=result, decision=decision, slim_user_input=slim_user_input),
                    index=0,
                    state=state,
                    decision=decision,
                    execution_instruction=execution_instruction,
                )
            ]
        agent_graph = result.get("agent_graph") if isinstance(result.get("agent_graph"), dict) else self.build_agent_graph(normalized_steps)
        workflow = result.get("workflow") if isinstance(result.get("workflow"), dict) else {}
        workflow.setdefault("workflow_id", "runtime_workflow")
        workflow.setdefault("status", "ready")
        workflow.setdefault("graph_type", "main_with_optional_subgraphs")
        result.update({
            "workflow": workflow,
            "planned_steps": normalized_steps,
            "agent_graph": agent_graph,
            "execution_decision": decision,
            "execution_plan": {
                "locked": True,
                "selected_action_type": decision.get("selected_action_type"),
                "ranked_options": decision.get("ranked_options"),
                "steps": normalized_steps,
                "allowed_action_types": self.fixed_action_types(),
                "selection_rules": list(SELECTION_RULES),
            },
            "required_capabilities": list(dict.fromkeys([str(s.get("required_capability") or "generic_runtime_capability") for s in normalized_steps])),
            "blocking_missing_information": result.get("blocking_missing_information") if isinstance(result.get("blocking_missing_information"), list) else [],
            "planning_contract": {
                "status": "locked",
                "workflow_planning_owns_action_selection": True,
                "execution_must_follow_locked_action": True,
                "fixed_execution_options": fixed_options_for_prompt(),
            },
            "status": result.get("status") or "planned",
            "message": result.get("message") or "Workflow planned with locked execution decision.",
        })
        return result

    def extract_execution_decision(self, container: dict[str, Any]) -> dict[str, Any]:
        """Find the first valid fixed-action decision in a generic nested record.

        LLM adapters often wrap their real output like:
        action_planning_record.action_planning_record.planned_steps[].
        This method is intentionally structural and domain-neutral: it only
        accepts values that map to the fixed action list. It never guesses from
        business words or intent labels.
        """
        for candidate in self.iter_nested_dicts(container, max_depth=8):
            for key in ("execution_decision", "execution_method_decision", "method_decision"):
                value = candidate.get(key)
                if isinstance(value, dict):
                    normalized = self.normalize_decision(value)
                    if normalized.get("selected_action_type"):
                        return normalized
            selected = normalize_action_type(
                candidate.get("selected_action_type")
                or candidate.get("action_type")
                or candidate.get("execution_action")
                or candidate.get("selected_option")
            )
            if is_fixed_action(selected):
                return self.normalize_decision({
                    "selected_action_type": selected,
                    "ranked_options": candidate.get("ranked_options") if isinstance(candidate.get("ranked_options"), list) else [{"action_type": selected, "priority": 1}],
                })
        return {}


    def extract_execution_instruction(self, container: dict[str, Any]) -> str:
        """Extract a generic executor-facing instruction from planner output.

        Planner stages may describe the requested final deliverable in nested
        ranking/substep records while the normalized step objective remains a
        broad capability statement.  The executor needs the concrete deliverable
        instruction, but must not use planner text as the final answer.
        """
        fragments: list[str] = []
        seen: set[str] = set()

        def add(value: Any) -> None:
            if value in (None, "", [], {}):
                return
            if isinstance(value, str):
                text = " ".join(value.strip().split())
                if text and text not in seen:
                    seen.add(text)
                    fragments.append(text)
            elif isinstance(value, dict):
                compact = {str(k): v for k, v in value.items() if v not in (None, "", [], {})}
                if compact:
                    text = str(compact)
                    if text not in seen:
                        seen.add(text)
                        fragments.append(text)
            elif isinstance(value, list):
                for item in value[:8]:
                    add(item)

        for candidate in self.iter_nested_dicts(container, max_depth=8):
            if not isinstance(candidate, dict):
                continue
            if self.extract_execution_decision(candidate).get("selected_action_type") == "llm_generate" or normalize_action_type(candidate.get("action_type")) == "llm_generate":
                for key in ("content", "instruction", "objective", "request", "task"):
                    add(candidate.get(key))
                params = candidate.get("parameters")
                if isinstance(params, dict):
                    add(params)
            substeps = candidate.get("substep_generation")
            if isinstance(substeps, list):
                add(substeps)
        return "\n".join(fragments)[:2000]

    def extract_planned_steps(self, container: dict[str, Any]) -> list[dict[str, Any]]:
        """Return the deepest valid planned_steps array from nested output.

        A valid step is a dict containing either a fixed action field or an
        embedded execution_decision. This prevents wrapper-level empty or
        fallback steps from overriding the actual planner decision.
        """
        best: list[dict[str, Any]] = []
        best_score = -1
        for candidate in self.iter_nested_dicts(container, max_depth=8):
            steps = candidate.get("planned_steps")
            if not isinstance(steps, list) or not steps:
                continue
            dict_steps = [step for step in steps if isinstance(step, dict)]
            if not dict_steps:
                continue
            score = 0
            for step in dict_steps:
                if self.extract_execution_decision(step).get("selected_action_type"):
                    score += 3
                elif is_fixed_action(normalize_action_type(step.get("action_type") or step.get("execution_action") or step.get("selected_action_type"))):
                    score += 2
                if step.get("parameters") or step.get("target") or step.get("objective"):
                    score += 1
            if score > best_score:
                best = dict_steps
                best_score = score
        return best

    def iter_nested_dicts(self, value: Any, *, max_depth: int = 8):
        if max_depth < 0:
            return
        if isinstance(value, dict):
            yield value
            for nested in value.values():
                yield from self.iter_nested_dicts(nested, max_depth=max_depth - 1)
        elif isinstance(value, list):
            for item in value:
                yield from self.iter_nested_dicts(item, max_depth=max_depth - 1)

    def normalize_decision(self, decision: dict[str, Any]) -> dict[str, Any]:
        ranked_raw = decision.get("ranked_options") if isinstance(decision.get("ranked_options"), list) else []
        ranked: list[dict[str, Any]] = []
        seen: set[str] = set()
        for i, item in enumerate(ranked_raw):
            if not isinstance(item, dict):
                continue
            action = normalize_action_type(item.get("action_type") or item.get("selected_action_type") or item.get("id") or item.get("name"))
            if not is_fixed_action(action) or action in seen:
                continue
            contract = ACTION_CONTRACTS.get(action, {})
            ranked.append({**contract, **item, "action_type": action, "priority": int(item.get("priority") or item.get("rank") or i + 1)})
            seen.add(action)
        selected = normalize_action_type(decision.get("selected_action_type") or decision.get("action_type") or decision.get("selected_option"))
        if not is_fixed_action(selected) and ranked:
            selected = str(ranked[0].get("action_type"))
        if not is_fixed_action(selected):
            return {}
        for action, contract in ACTION_CONTRACTS.items():
            if action not in seen:
                ranked.append({**contract, "action_type": action, "priority": len(ranked) + 1, "reason": "available fixed execution option"})
        ranked.sort(key=lambda x: int(x.get("priority") or 999))
        return {
            "selected_action_type": selected,
            "selected_execution_method": method_for_action(selected),
            "ranked_options": ranked,
            "selection_rules": list(SELECTION_RULES),
        }

    def _joined_request_text(self, *, state: dict[str, Any], result: dict[str, Any], container: dict[str, Any] | None = None) -> str:
        """Collect generic request text for structural action-policy checks.

        This is not domain or business logic. It only decides whether the
        selected fixed action asks for a reusable runtime artifact when the
        upstream text appears to request a final human-readable deliverable.
        """
        parts: list[str] = []
        for value in (state.get("input"), result.get("message") if isinstance(result, dict) else None, result.get("objective") if isinstance(result, dict) else None):
            if value not in (None, ""):
                parts.append(str(value))
        results = state.get("results") if isinstance(state.get("results"), dict) else {}
        for key in ("input_parsing", "intent_recognition", "requirement_completion", "context_awareness"):
            value = results.get(key)
            if isinstance(value, dict):
                for field in ("original_input", "recognized_intent", "classified_intent", "intent", "objective", "intent_summary"):
                    if value.get(field) not in (None, ""):
                        parts.append(str(value.get(field)))
                data = value.get("data") if isinstance(value.get("data"), dict) else {}
                for field in ("classified_intent", "normalized_input", "intent"):
                    if data.get(field) not in (None, ""):
                        parts.append(str(data.get(field)))
        if isinstance(container, dict):
            for field in ("content", "objective", "target", "action", "message"):
                if container.get(field) not in (None, ""):
                    parts.append(str(container.get(field)))
        return "\n".join(parts).casefold()

    def _looks_like_final_text_deliverable(self, text: str) -> bool:
        """Return False without vocabulary inference.

        ai_core must not infer task meaning from embedded keyword lists.
        Output-vs-artifact decisions must come from runtime semantic planning,
        schemas, or model-produced normalized contracts.
        """
        return False

    def _correct_action_for_output_contract(self, *, action_type: str, state: dict[str, Any], result: dict[str, Any], container: dict[str, Any] | None = None) -> str:
        """Prevent accidental runtime-artifact generation for direct output tasks.

        The LLM still chooses the action. This guard only enforces the fixed
        action contract when a reusable runtime artifact was selected without
        an artifact-shaped request. It does not include business/domain terms.
        """
        if action_type not in {"generate_code", "generate_complex_tool"}:
            return action_type
        text = self._joined_request_text(state=state, result=result, container=container)
        if self._looks_like_final_text_deliverable(text):
            return "llm_generate"
        return action_type

    def default_execution_decision(self, *, state: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        results = state.get("results") if isinstance(state.get("results"), dict) else {}
        for value in (result, results.get("intent_recognition"), results.get("context_awareness"), results.get("requirement_completion"), results.get("input_parsing")):
            if isinstance(value, dict):
                extracted = self.extract_execution_decision(value)
                if extracted.get("selected_action_type"):
                    return extracted
        selected = self.default_action_from_structural_context(state=state, result=result)
        ranked = []
        for i, item in enumerate(fixed_options_for_prompt()):
            priority = 1 if item["action_type"] == selected else i + 2
            reason = "selected by structural fallback after planner did not return one fixed action"
            ranked.append({**item, "priority": priority, "reason": reason})
        ranked.sort(key=lambda x: int(x["priority"]))
        return {"selected_action_type": selected, "selected_execution_method": method_for_action(selected), "ranked_options": ranked, "selection_rules": list(SELECTION_RULES), "decision_source": "structural_fallback"}

    def default_action_from_structural_context(self, *, state: dict[str, Any], result: dict[str, Any]) -> str:
        """Choose a safe fixed action using only generic runtime structure.

        This is intentionally domain-neutral.  It does not inspect business
        words.  It only checks whether more user input is structurally missing,
        whether an uploaded/local artifact is explicitly available as an
        execution method, and whether planner output contains executor-facing
        material that can be turned into a content-generation contract.
        """
        if self.has_missing_required_input(state=state, result=result):
            return "ask_user"
        if self.referenced_artifacts_for_state(state, ""):
            return "use_uploaded_file"
        if self.extract_execution_instruction(result):
            return "llm_generate"
        known = self.collect_known_parameters(state)
        if known:
            return "llm_generate"
        return "ask_user"

    def has_missing_required_input(self, *, state: dict[str, Any], result: dict[str, Any]) -> bool:
        if self.allows_research_to_resolve_missing(state=state, result=result):
            return False
        for container in (result, state.get("results") if isinstance(state.get("results"), dict) else {}):
            for candidate in self.iter_nested_dicts(container, max_depth=6):
                for key in ("missing_required", "missing_information", "blocking_missing_information", "missing_fields"):
                    value = candidate.get(key) if isinstance(candidate, dict) else None
                    if isinstance(value, dict) and any(v not in (None, "", [], {}) for v in value.values()):
                        return True
                    if isinstance(value, list) and any(v not in (None, "", [], {}) for v in value):
                        return True
        return False


    def allows_research_to_resolve_missing(self, *, state: dict[str, Any], result: dict[str, Any]) -> bool:
        containers = [result]
        results = state.get("results") if isinstance(state.get("results"), dict) else {}
        containers.append(results)
        for container in containers:
            for candidate in self.iter_nested_dicts(container, max_depth=6):
                if not isinstance(candidate, dict):
                    continue
                if bool(candidate.get("capability_gap_detected")):
                    return True
                intent_type = str(candidate.get("intent_type") or candidate.get("classified_intent") or "").casefold()
                signals = candidate.get("external_information_signals") if isinstance(candidate.get("external_information_signals"), list) else []
                signal_text = " ".join(str(x).casefold() for x in signals)
                if ("capability_gap" in intent_type or "runtime_capability" in intent_type or "capability_gap" in signal_text) and bool(candidate.get("requires_external_information") or candidate.get("needs_external_execution")):
                    return True
        return False

    def default_step(self, *, state: dict[str, Any], result: dict[str, Any], decision: dict[str, Any], slim_user_input: str) -> dict[str, Any]:
        known = self.collect_known_parameters(state)
        objective = self.objective_from_state(state=state, result=result, slim_user_input=slim_user_input)
        action_type = str(decision.get("selected_action_type") or "llm_generate")
        action_type = self._correct_action_for_output_contract(action_type=action_type, state=state, result=result, container=decision)
        if action_type != decision.get("selected_action_type"):
            decision = {**decision, "selected_action_type": action_type, "selected_execution_method": method_for_action(action_type), "selection_guard": "corrected_to_direct_output_generation"}
        return {
            "step_id": "step_1",
            "task_id": "step_1",
            "step_type": "runtime_execution",
            "action": "execute_selected_runtime_action",
            "action_type": action_type,
            "objective": objective,
            "input_from": ["input_parsing", "intent_recognition", "requirement_completion", "context_awareness"],
            "parameters": {"known": known, "missing_required": {}, "optional": {}},
            "required_capability": self.capability_from_state(state),
            "execution_decision": decision,
            "agent_action_prompt_contract": AGENT_ACTION_PROMPT_CONTRACT,
            "agent_execution_flow": self.default_agent_execution_flow(action_type=action_type),
            "execution_ready": True,
            "human_interaction": {},
            "next_action": "execution_preparation",
            "depends_on": [],
            "requires_human_confirmation": False,
            "missing_fields": [],
        }

    def collect_available_artifacts(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        artifacts: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add_item(item: dict[str, Any]) -> None:
            artifact_id = str(item.get("artifact_id") or item.get("id") or item.get("path") or item.get("filename") or "").strip()
            path = str(item.get("path") or item.get("filepath") or item.get("file_path") or "").strip()
            filename = str(item.get("filename") or item.get("name") or "").strip()
            key_id = artifact_id or path or filename
            if key_id and key_id not in seen:
                seen.add(key_id)
                artifacts.append(dict(item))

        # Registry items are runtime resources, not business logic. Include them
        # so a user-visible filename mentioned in the request can be resolved even
        # when the UI did not explicitly attach the artifact to the message body.
        for item in self.artifact_registry.list():
            if isinstance(item, dict):
                add_item(item)

        def visit(value: Any, depth: int = 0) -> None:
            if depth > 6:
                return
            if isinstance(value, dict):
                for key in ("uploaded_artifacts", "available_artifacts", "artifact_refs", "source_files", "method_files"):
                    raw = value.get(key)
                    if isinstance(raw, list):
                        for item in raw:
                            if isinstance(item, dict):
                                add_item(item)
                for nested in value.values():
                    visit(nested, depth + 1)
            elif isinstance(value, list):
                for item in value:
                    visit(item, depth + 1)
        visit(state)
        return artifacts

    def referenced_artifacts_for_state(self, state: dict[str, Any], text: str = "") -> list[dict[str, Any]]:
        artifacts = self.collect_available_artifacts(state)
        request_text = (str(text or "") + " " + self._joined_request_text(state=state, result={}, container={})).strip()
        if not request_text:
            return []
        matched: list[dict[str, Any]] = []
        registry_matches = self.artifact_registry.resolve_from_text(request_text)
        for item in registry_matches:
            if isinstance(item, dict):
                matched.append(dict(item))
        for item in artifacts:
            names = [
                str(item.get("artifact_id") or item.get("id") or ""),
                str(item.get("filename") or ""),
                str(item.get("name") or ""),
            ]
            path = str(item.get("path") or "")
            if path:
                names.append(path.split("/")[-1].split("\\")[-1])
            if any(name and name.lower() in request_text.lower() for name in names):
                matched.append(dict(item))
        return matched

    def artifact_forced_decision(self, state: dict[str, Any], slim_user_input: str = "") -> dict[str, Any]:
        refs = self.referenced_artifacts_for_state(state, slim_user_input)
        if not refs:
            return {}
        selected = "use_uploaded_file"
        ranked = [{**ACTION_CONTRACTS[selected], "action_type": selected, "priority": 1, "reason": "request references an available uploaded artifact as execution method"}]
        for action, contract in ACTION_CONTRACTS.items():
            if action != selected:
                ranked.append({**contract, "action_type": action, "priority": len(ranked) + 1, "reason": "available fixed execution option"})
        return {
            "selected_action_type": selected,
            "selected_execution_method": method_for_action(selected),
            "ranked_options": ranked,
            "selection_rules": list(SELECTION_RULES),
            "artifact_refs": refs,
            "decision_guard": "available_uploaded_artifact_reference",
        }

    def normalize_step(self, *, step: dict[str, Any], index: int, state: dict[str, Any], decision: dict[str, Any], execution_instruction: str = "") -> dict[str, Any]:
        out = dict(step)
        step_id = str(out.get("step_id") or out.get("task_id") or f"step_{index + 1}")
        out["step_id"] = step_id
        out.setdefault("task_id", step_id)
        out.setdefault("step_type", "runtime_execution")
        out.setdefault("input_from", ["input_parsing", "intent_recognition", "requirement_completion", "context_awareness"])
        out.setdefault("objective", self.objective_from_state(state=state, result={}, slim_user_input=""))
        params = out.get("parameters") if isinstance(out.get("parameters"), dict) else {}
        if not any(k in params for k in ("known", "missing_required", "optional")):
            params = {"known": params, "missing_required": {}, "optional": {}}
        else:
            params = {
                "known": params.get("known") if isinstance(params.get("known"), dict) else {},
                "missing_required": params.get("missing_required") if isinstance(params.get("missing_required"), (dict, list)) else {},
                "optional": params.get("optional") if isinstance(params.get("optional"), dict) else {},
            }
        if not params["known"]:
            params["known"] = self.collect_known_parameters(state)
        out["parameters"] = params
        artifact_refs = decision.get("artifact_refs") if isinstance(decision.get("artifact_refs"), list) else self.referenced_artifacts_for_state(state, str(out.get("objective") or ""))
        if artifact_refs:
            existing_refs = out.get("uploaded_artifacts") if isinstance(out.get("uploaded_artifacts"), list) else []
            out["uploaded_artifacts"] = existing_refs or artifact_refs
            out["artifact_refs"] = artifact_refs
            out.setdefault("external_artifact", {"artifact_refs": artifact_refs})
        step_decision = self.extract_execution_decision(out) or decision
        action_type = normalize_action_type(out.get("action_type") or out.get("execution_action") or step_decision.get("selected_action_type"))
        if not is_fixed_action(action_type):
            action_type = normalize_action_type(decision.get("selected_action_type"), "ask_user")
        if artifact_refs:
            action_type = "use_uploaded_file"
        corrected_action_type = self._correct_action_for_output_contract(action_type=action_type, state=state, result={}, container=out)
        if corrected_action_type != action_type:
            action_type = corrected_action_type
            step_decision = {**(step_decision or decision), "selected_action_type": action_type, "selected_execution_method": method_for_action(action_type), "selection_guard": "corrected_to_direct_output_generation"}
        method = method_for_action(action_type)
        out["action_type"] = action_type
        out["execution_action"] = action_type
        out["execution_decision"] = step_decision or decision
        if execution_instruction and method == "content_generation":
            out.setdefault("execution_instruction", execution_instruction)
            out.setdefault("prompt_contract", {})
            if isinstance(out["prompt_contract"], dict):
                out["prompt_contract"].setdefault("executor_instruction", execution_instruction)
        out["agent_action_prompt_contract"] = AGENT_ACTION_PROMPT_CONTRACT
        out["execution_method"] = method
        out["execution_method_policy"] = {"preferred_methods": [method], "disabled_methods": [m for m in set(ACTION_TO_METHOD.values()) if m != method], "fallback_allowed": False}
        out["execution_strategy"] = [method]
        out.setdefault("required_capability", self.capability_from_state(state))
        out.setdefault("execution_ready", not bool(params.get("missing_required")))
        out.setdefault("human_interaction", {})
        out.setdefault("next_action", "execution_preparation")
        out.setdefault("depends_on", [])
        out.setdefault("requires_human_confirmation", False)
        out.setdefault("missing_fields", [])
        out["agent_execution_flow"] = self.extract_agent_execution_flow(out, action_type=action_type)
        out["source_policy"] = self.source_policy_for_method(method)
        return out


    def extract_agent_execution_flow(self, container: dict[str, Any], *, action_type: str) -> list[dict[str, Any]]:
        """Extract or synthesize a domain-neutral agent execution flow.

        The flow is planning material used by later stages. It is not final
        answer material. It records why planner LLM calls are made, what
        resource discovery is expected to produce, and which concrete action
        should be executed next.
        """
        for candidate in self.iter_nested_dicts(container, max_depth=8):
            flow = candidate.get("agent_execution_flow") or candidate.get("execution_flow") or candidate.get("substeps")
            if isinstance(flow, list) and any(isinstance(item, dict) for item in flow):
                return [dict(item) for item in flow if isinstance(item, dict)]
        return self.default_agent_execution_flow(action_type=action_type)

    def default_agent_execution_flow(self, *, action_type: str) -> list[dict[str, Any]]:
        method = method_for_action(action_type)
        flow: list[dict[str, Any]] = [
            {
                "phase_id": "phase_1",
                "phase_role": "planner_llm_action_selection",
                "action_type": "planner_llm",
                "purpose": "rank fixed actions and choose the next concrete execution action",
                "inputs": ["input_record", "intent_record", "requirement_record", "clean_context", "agent_objective"],
                "outputs": ["execution_decision", "ranked_options", "selected_action_type"],
                "success_criteria": ["selected_action_type is one fixed action", "planned_steps are produced"],
                "next_on_success": "phase_2",
                "next_on_failure": "repair_or_ask_user",
            }
        ]
        if action_type == "llm_generate" or method == "content_generation":
            flow.append({
                "phase_id": "phase_2",
                "phase_role": "prompt_contract_preparation",
                "action_type": "llm_generate",
                "execution_method": "content_generation",
                "purpose": "build a prompt contract from the objective and confirmed parameters without executing during planning",
                "inputs": ["selected_action_type", "known_parameters", "objective"],
                "outputs": ["prompt_contract", "model_route", "generation_constraints"],
                "success_criteria": ["prompt contract contains objective and confirmed parameters", "planner output is not used as final content"],
                "next_on_success": "phase_3",
                "next_on_failure": "feedback_repair",
            })
            flow.append({
                "phase_id": "phase_3",
                "phase_role": "output_contract_preparation",
                "action_type": "llm_generate",
                "execution_method": "content_generation",
                "purpose": "define expected final material and verification criteria for generated content",
                "inputs": ["prompt_contract", "known_parameters"],
                "outputs": ["output_contract", "verification_contract"],
                "success_criteria": ["output contract is explicit", "verification criteria can be checked after execution"],
                "next_on_success": "phase_4",
                "next_on_failure": "feedback_repair",
            })
            flow.append({
                "phase_id": "phase_4",
                "phase_role": "executor_llm_generation",
                "action_type": "llm_generate",
                "execution_method": "content_generation",
                "purpose": "call the executor LLM to produce the final requested content",
                "inputs": ["prompt_contract", "output_contract", "validation_record"],
                "outputs": ["answer_material", "execution_record"],
                "success_criteria": ["answer_material is generated by executor LLM", "no runtime observation is substituted"],
                "next_on_success": "result_verification",
                "next_on_failure": "feedback_repair",
            })
        elif method in {"web_search", "api_call"}:
            flow.append({
                "phase_id": "phase_2",
                "phase_role": "resource_discovery",
                "action_type": "web_query" if method == "web_search" else action_type,
                "purpose": "collect available pages, API candidates, credential requirements, query targets, and evidence URL policy before real execution",
                "inputs": ["selected_action_type", "known_parameters", "candidate_targets"],
                "outputs": ["query_contract", "candidate_sources", "candidate_endpoints", "credential_requirements", "evidence_requirements"],
                "success_criteria": ["candidate URLs are preserved", "credential requirements are explicit", "source URLs can be verified after execution"],
                "next_on_success": "phase_3",
                "next_on_failure": "resource_discovery_repair",
            })
            flow.append({
                "phase_id": "phase_3",
                "phase_role": "api_or_web_contract_preparation",
                "action_type": action_type,
                "purpose": "convert discovered candidates into an executable API contract when possible; otherwise prepare a web extraction contract; if credentials are required, prepare a UI credential request",
                "inputs": ["candidate_sources", "candidate_endpoints", "credential_requirements", "known_parameters"],
                "outputs": ["api_contract", "web_extract_contract", "credential_request", "resource_bundle"],
                "success_criteria": ["no-key candidates are preferred", "key-required candidates trigger user interaction before execution", "prepared contract matches selected action"],
                "next_on_success": "phase_4",
                "next_on_failure": "credential_or_contract_repair",
            })
            flow.append({
                "phase_id": "phase_4",
                "phase_role": "real_execution",
                "action_type": action_type,
                "execution_method": method,
                "purpose": "execute only the locked prepared resource contract",
                "inputs": ["resource_bundle", "validation_record"],
                "outputs": ["execution_record", "provenance", "evidence_urls"],
                "success_criteria": ["result comes from executed resource", "provenance contains source information"],
                "next_on_success": "result_verification",
                "next_on_failure": "feedback_repair",
            })
        else:
            flow.append({
                "phase_id": "phase_2",
                "phase_role": "resource_preparation",
                "action_type": action_type,
                "execution_method": method,
                "purpose": "prepare the resource contract required by the locked action",
                "inputs": ["selected_action_type", "known_parameters"],
                "outputs": ["resource_bundle"],
                "success_criteria": ["resource bundle matches selected action"],
                "next_on_success": "phase_3",
                "next_on_failure": "feedback_repair",
            })
            flow.append({
                "phase_id": "phase_3",
                "phase_role": "real_execution",
                "action_type": action_type,
                "execution_method": method,
                "purpose": "execute the prepared locked action",
                "inputs": ["resource_bundle", "validation_record"],
                "outputs": ["execution_record", "provenance"],
                "success_criteria": ["execution result is produced by the selected action"],
                "next_on_success": "result_verification",
                "next_on_failure": "feedback_repair",
            })
        return flow

    def source_policy_for_method(self, method: str) -> dict[str, Any]:
        return {
            "allow_external": method in {"api_call", "web_search", "external_skill"},
            "allow_internal": True,
            "requires_live_evidence": method in {"api_call", "web_search"},
        }

    def build_agent_graph(self, steps: list[dict[str, Any]]) -> dict[str, Any]:
        nodes = []
        edges = []
        for step in steps:
            step_id = str(step.get("step_id"))
            deps = step.get("depends_on") if isinstance(step.get("depends_on"), list) else []
            nodes.append({"id": step_id, "relation": "dependent" if deps else "independent", "execution_method": step.get("execution_method"), "action_type": step.get("action_type")})
            for dep in deps:
                edges.append({"from": str(dep), "to": step_id, "context_policy": "strict_json_safe_summary"})
        return {"main_graph": {"nodes": nodes, "edges": edges}, "subgraphs": []}

    def collect_known_parameters(self, state: dict[str, Any]) -> dict[str, Any]:
        known: dict[str, Any] = {}
        results = state.get("results") if isinstance(state.get("results"), dict) else {}
        candidates = []
        for node in ("context_awareness", "requirement_completion", "intent_recognition", "input_parsing"):
            value = results.get(node) if isinstance(results.get(node), dict) else {}
            candidates.append(value)
            for key in ("context_record", "requirement_record", "intent_record", "input_record"):
                if isinstance(value.get(key), dict):
                    candidates.append(value[key])
        for record in candidates:
            for key in ("known_parameters", "parsed_entities", "normalized_intent", "parameters"):
                value = record.get(key) if isinstance(record, dict) else None
                if isinstance(value, dict):
                    nested = value.get("known") if isinstance(value.get("known"), dict) else value
                    for k, v in nested.items():
                        if v not in (None, "", [], {}):
                            known[str(k)] = v
            clean = record.get("clean_context") if isinstance(record.get("clean_context"), dict) else {}
            if isinstance(clean.get("known_parameters"), dict):
                known.update({str(k): v for k, v in clean["known_parameters"].items() if v not in (None, "", [], {})})
        return known

    def objective_from_state(self, *, state: dict[str, Any], result: dict[str, Any], slim_user_input: str) -> str:
        results = state.get("results") if isinstance(state.get("results"), dict) else {}
        intent = results.get("intent_recognition") if isinstance(results.get("intent_recognition"), dict) else {}
        parsed = results.get("input_parsing") if isinstance(results.get("input_parsing"), dict) else {}
        return str(result.get("objective") or intent.get("intent_summary") or intent.get("objective") or parsed.get("original_input") or state.get("input") or slim_user_input or "execute requested task")[:1000]

    def capability_from_state(self, state: dict[str, Any]) -> str:
        results = state.get("results") if isinstance(state.get("results"), dict) else {}
        intent = results.get("intent_recognition") if isinstance(results.get("intent_recognition"), dict) else {}
        for key in ("intent_type", "classified_intent", "intent", "name"):
            value = intent.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:120]
        return "generic_runtime_capability"
