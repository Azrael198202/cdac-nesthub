from __future__ import annotations

from typing import Any

from ai_core.workflow.execution_options import ACTION_CONTRACTS, ACTION_TO_METHOD, SELECTION_RULES, fixed_options_for_prompt, is_fixed_action, method_for_action


class WorkflowContractBuilder:
    """Domain-neutral workflow output normalizer.

    It guarantees that workflow_planning produces a locked execution_plan with
    planned_steps, agent_graph, ranked execution options, and source policy.
    It never decides business semantics; it only uses upstream structured
    intent/context and fixed runtime action options.
    """

    def fixed_action_types(self) -> list[str]:
        return list(ACTION_TO_METHOD.keys())

    def normalize_workflow_result(self, *, result: dict[str, Any], state: dict[str, Any], slim_user_input: str = "") -> dict[str, Any]:
        if not isinstance(result, dict):
            result = {}
        decision = self.extract_execution_decision(result)
        if not decision.get("selected_action_type"):
            decision = self.default_execution_decision(state=state, result=result)
        steps = result.get("planned_steps") if isinstance(result.get("planned_steps"), list) else []
        if not steps:
            steps = [self.default_step(state=state, result=result, decision=decision, slim_user_input=slim_user_input)]
        normalized_steps = [self.normalize_step(step=step, index=index, state=state, decision=decision) for index, step in enumerate(steps) if isinstance(step, dict)]
        if not normalized_steps:
            normalized_steps = [self.normalize_step(step=self.default_step(state=state, result=result, decision=decision, slim_user_input=slim_user_input), index=0, state=state, decision=decision)]
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
        if not isinstance(container, dict):
            return {}
        for key in ("execution_decision", "execution_method_decision", "method_decision"):
            value = container.get(key)
            if isinstance(value, dict):
                return self.normalize_decision(value)
        plan = container.get("execution_plan") if isinstance(container.get("execution_plan"), dict) else {}
        for key in ("execution_decision", "execution_method_decision", "method_decision"):
            value = plan.get(key)
            if isinstance(value, dict):
                return self.normalize_decision(value)
        return {}

    def normalize_decision(self, decision: dict[str, Any]) -> dict[str, Any]:
        ranked_raw = decision.get("ranked_options") if isinstance(decision.get("ranked_options"), list) else []
        ranked: list[dict[str, Any]] = []
        seen: set[str] = set()
        for i, item in enumerate(ranked_raw):
            if not isinstance(item, dict):
                continue
            action = str(item.get("action_type") or item.get("selected_action_type") or item.get("id") or item.get("name") or "").strip()
            if not is_fixed_action(action) or action in seen:
                continue
            contract = ACTION_CONTRACTS.get(action, {})
            ranked.append({**contract, **item, "action_type": action, "priority": int(item.get("priority") or item.get("rank") or i + 1)})
            seen.add(action)
        selected = str(decision.get("selected_action_type") or decision.get("action_type") or decision.get("selected_option") or "").strip()
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

    def default_execution_decision(self, *, state: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        results = state.get("results") if isinstance(state.get("results"), dict) else {}
        for value in (result, results.get("intent_recognition"), results.get("context_awareness"), results.get("requirement_completion"), results.get("input_parsing")):
            if isinstance(value, dict):
                extracted = self.extract_execution_decision(value)
                if extracted.get("selected_action_type"):
                    return extracted
        selected = "call_llm"
        ranked = []
        for i, item in enumerate(fixed_options_for_prompt()):
            priority = 1 if item["action_type"] == selected else i + 2
            ranked.append({**item, "priority": priority, "reason": "default generic option when model did not provide a valid fixed action"})
        ranked.sort(key=lambda x: int(x["priority"]))
        return {"selected_action_type": selected, "selected_execution_method": method_for_action(selected), "ranked_options": ranked, "selection_rules": list(SELECTION_RULES)}

    def default_step(self, *, state: dict[str, Any], result: dict[str, Any], decision: dict[str, Any], slim_user_input: str) -> dict[str, Any]:
        known = self.collect_known_parameters(state)
        objective = self.objective_from_state(state=state, result=result, slim_user_input=slim_user_input)
        action_type = str(decision.get("selected_action_type") or "call_llm")
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
            "execution_ready": True,
            "human_interaction": {},
            "next_action": "execution_preparation",
            "depends_on": [],
            "requires_human_confirmation": False,
            "missing_fields": [],
        }

    def normalize_step(self, *, step: dict[str, Any], index: int, state: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
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
        step_decision = self.extract_execution_decision(out) or decision
        action_type = str(out.get("action_type") or out.get("execution_action") or step_decision.get("selected_action_type") or "").strip()
        if not is_fixed_action(action_type):
            action_type = str(decision.get("selected_action_type") or "call_llm")
        method = method_for_action(action_type)
        out["action_type"] = action_type
        out["execution_action"] = action_type
        out["execution_decision"] = step_decision or decision
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
        out["source_policy"] = self.source_policy_for_method(method)
        return out

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
