from __future__ import annotations

from copy import deepcopy
from typing import Any


class IntentContractGuard:
    """Creates and enforces a stage-boundary contract from intent output.

    The contract is intentionally domain-neutral.  It does not know concrete
    business words.  It only uses structural signals produced by upstream
    stages, such as intent type, normalized parameters, and whether a later
    capability was inferred rather than explicitly planned.
    """

    RUNTIME_OBSERVATION_CAPABILITY = "runtime_current_observation"

    def build(self, previous_results: dict[str, Any]) -> dict[str, Any]:
        intent = previous_results.get("intent_recognition") if isinstance(previous_results, dict) else {}
        parsed = previous_results.get("input_parsing") if isinstance(previous_results, dict) else {}
        if not isinstance(intent, dict):
            intent = {}
        if not isinstance(parsed, dict):
            parsed = {}
        intent_type = str(intent.get("intent_type") or "").strip()
        normalized = intent.get("normalized_intent") if isinstance(intent.get("normalized_intent"), dict) else {}
        parsed_entities = parsed.get("parsed_entities") if isinstance(parsed.get("parsed_entities"), dict) else {}
        temporal_expressions = parsed.get("temporal_expressions") if isinstance(parsed.get("temporal_expressions"), list) else []
        target_values = self._target_values(normalized, parsed_entities, temporal_expressions)
        family = self._intent_family(intent_type=intent_type, normalized=normalized, parsed=parsed)
        return {
            "status": "locked" if intent_type else "empty",
            "intent_type": intent_type,
            "intent_family": family,
            "normalized_intent": deepcopy(normalized),
            "parsed_entities": deepcopy(parsed_entities),
            "target_values": target_values,
            "source_nodes": ["input_parsing", "intent_recognition"],
            "rules": {
                "downstream_may_refine": True,
                "downstream_may_replace_intent": False,
                "inferred_capability_must_not_conflict": True,
                "execution_method_must_follow_contract": True,
            },
        }

    def apply(self, workflow_plan: dict[str, Any], previous_results: dict[str, Any]) -> dict[str, Any]:
        plan = deepcopy(workflow_plan or {})
        contract = self.build(previous_results)
        steps = plan.get("planned_steps") if isinstance(plan.get("planned_steps"), list) else []
        guarded_steps: list[dict[str, Any]] = []
        guard_events: list[dict[str, Any]] = []

        for raw_step in steps:
            step = deepcopy(raw_step) if isinstance(raw_step, dict) else {}
            before = deepcopy(step)
            step = self._guard_step(step, contract)
            event = step.pop("_intent_guard_event", None)
            if event:
                guard_events.append({"step_id": step.get("step_id") or step.get("task_id"), **event, "before": before, "after": deepcopy(step)})
            step.setdefault("intent_contract_ref", {
                "intent_type": contract.get("intent_type"),
                "intent_family": contract.get("intent_family"),
                "target_values": contract.get("target_values", []),
            })
            guarded_steps.append(step)

        plan["planned_steps"] = guarded_steps
        plan["intent_contract"] = contract
        plan["workflow_intent_guard"] = {
            "status": "checked",
            "event_count": len(guard_events),
            "events": guard_events,
        }
        return plan

    def _guard_step(self, step: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
        family = str(contract.get("intent_family") or "")
        capability = str(step.get("required_capability") or "").strip()
        inference = step.get("capability_inference") if isinstance(step.get("capability_inference"), dict) else {}
        inferred = bool(inference) and str(inference.get("status") or "") == "inferred"
        strategy = step.get("execution_strategy") if isinstance(step.get("execution_strategy"), list) else []

        # A locked upstream contract is stronger than downstream capability
        # similarity.  The guard applies to the whole family, not just to one
        # concrete capability name, so later stages cannot drift from an
        # external-source task into a runtime-local observation.
        if family == "external_information":
            if inferred and capability == self.RUNTIME_OBSERVATION_CAPABILITY:
                step.pop("capability_inference", None)
                reason = "inferred_runtime_capability_conflicted_with_locked_intent_contract"
            else:
                reason = "external_information_contract_enforced"
            if capability == self.RUNTIME_OBSERVATION_CAPABILITY or not capability:
                step["required_capability"] = "generic_information_access"
            step["execution_strategy"] = self._ensure_external_strategy(strategy)
            step["semantic_category"] = "structured_external_observation"
            step["required_source_level"] = "external_content"
            step["execution_method_policy"] = {
                "preferred_methods": ["api_call", "web_search", "existing_tool"],
                "disabled_methods": ["runtime_generated_tool", "model_knowledge"],
                "fallback_allowed": True,
            }
            step["_intent_guard_event"] = {"status": "checked", "reason": reason}
            return step

        # Runtime-native observation contracts are kept strict.  If runtime is
        # selected, the executor must not silently fall back to external web
        # evidence, because that changes the source semantics.
        if family == "runtime_observation" or capability == self.RUNTIME_OBSERVATION_CAPABILITY:
            step["required_capability"] = self.RUNTIME_OBSERVATION_CAPABILITY
            step["semantic_category"] = "runtime_state_observation"
            step["execution_strategy"] = ["tool_generation", "local_knowledge"]
            step["execution_method_policy"] = {
                "preferred_methods": ["runtime_generated_tool", "existing_tool"],
                "disabled_methods": ["web_search", "api_call", "knowledge_base", "model_knowledge"],
                "fallback_allowed": False,
            }
            step["required_source_level"] = "runtime_native"
            step["_intent_guard_event"] = {"status": "checked", "reason": "runtime_observation_contract_enforced"}
        return step

    def _ensure_external_strategy(self, strategy: list[Any]) -> list[str]:
        values = [str(x).strip() for x in strategy if str(x).strip()]
        for value in ["structured_provider", "web_evidence"]:
            if value not in values:
                values.insert(0 if value == "structured_provider" else len(values), value)
        return values

    def _intent_family(self, *, intent_type: str, normalized: dict[str, Any], parsed: dict[str, Any]) -> str:
        text = " ".join([intent_type, *[str(k) for k in normalized.keys()], *[str(k) for k in parsed.keys()]]).casefold()
        # Generic category labels only. Concrete business terms are not encoded.
        has_external_targets = bool(normalized) and any(
            isinstance(v, (list, dict)) or str(v).strip()
            for v in normalized.values()
        )
        if ("current" in text or "runtime" in text or "remind" in text) and not ("information" in text and has_external_targets):
            return "runtime_observation"
        if "information" in text or "retrieval" in text or "lookup" in text or "search" in text:
            return "external_information"
        return "general"

    def _target_values(self, *items: Any) -> list[str]:
        values: list[str] = []
        def walk(value: Any) -> None:
            if isinstance(value, str):
                if value.strip():
                    values.append(value.strip())
            elif isinstance(value, (int, float)):
                values.append(str(value))
            elif isinstance(value, dict):
                for k, v in value.items():
                    if str(k).strip():
                        values.append(str(k).strip())
                    walk(v)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
        for item in items:
            walk(item)
        return list(dict.fromkeys(values))[:64]
