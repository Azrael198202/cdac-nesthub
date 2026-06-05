from __future__ import annotations

import json
import re
from typing import Any

from verification_brain.contracts import VerificationExpectation, VerificationResult
from ai_core.model_orchestration import LiteLLMBrainClient


_TEMPLATE_RE = re.compile(r"\{\{\s*[^{}]+\s*\}\}")


class RuntimeVerificationBrain:
    """Six-level deterministic verification before model-based judgment.

    v20 keeps verification generic and evidence-first.  The verifier does not
    contain business words and does not decide how to repair.  It only checks
    whether a runtime artifact/run satisfies structural contracts that every
    workflow should obey.

    Levels:
      1. Template verification
      2. Schema verification
      3. Dependency verification
      4. Capability verification
      5. Expectation verification
      6. Side-effect verification
    """

    LEVELS = {
        1: "template_verification",
        2: "schema_verification",
        3: "dependency_verification",
        4: "capability_verification",
        5: "expectation_verification",
        6: "side_effect_verification",
    }

    SUCCESS_STATUSES = {"completed", "succeeded", "success", "ok", "verified", "reused"}
    FAILURE_STATUSES = {"failed", "error", "blocked", "requires_input", "requires_key", "paused", "not_found"}

    def __init__(self) -> None:
        self.llm = LiteLLMBrainClient()

    def verify(self, *, output: Any, expectation: VerificationExpectation | dict[str, Any] | None = None) -> VerificationResult:
        exp = expectation if isinstance(expectation, VerificationExpectation) else VerificationExpectation(
            name=str((expectation or {}).get("name") or "generic_runtime_expectation"),
            rules=(expectation or {}).get("rules") if isinstance((expectation or {}).get("rules"), dict) else {},
        )
        rules = exp.rules
        context = output if isinstance(output, dict) else {"output": output}
        checks: list[dict[str, Any]] = []
        checks.extend(self._level1_template(context, rules))
        checks.extend(self._level2_schema(context, rules))
        checks.extend(self._level3_dependency(context, rules))
        checks.extend(self._level4_capability(context, rules))
        checks.extend(self._level5_expectation(context, rules))
        checks.extend(self._level6_side_effect(context, rules))
        passed = all(check.get("passed") is not False for check in checks) if checks else True
        return VerificationResult(passed=passed, status="verified" if passed else "verification_failed", checks=checks)

    def _level1_template(self, context: dict[str, Any], rules: dict[str, Any]) -> list[dict[str, Any]]:
        if not rules.get("must_not_contain_unresolved_template", True):
            return []
        text = self._stringify(context)
        matches = sorted(set(_TEMPLATE_RE.findall(text)))
        return [{
            "level": 1,
            "level_name": self.LEVELS[1],
            "name": "template_must_be_resolved",
            "passed": not matches,
            "unresolved_templates": matches[:30],
            "suggested_location": ["template resolution", "dependency mapping", "parameter hydration"],
        }]

    def _level2_schema(self, context: dict[str, Any], rules: dict[str, Any]) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []
        required_keys = rules.get("required_keys") if isinstance(rules.get("required_keys"), list) else []
        target = context.get("output") if isinstance(context.get("output"), dict) else context
        for key in required_keys:
            ok = isinstance(target, dict) and key in target and target.get(key) not in (None, "", [], {})
            checks.append({
                "level": 2,
                "level_name": self.LEVELS[2],
                "name": "required_key_present",
                "key": key,
                "passed": ok,
                "suggested_location": ["schema contract", "parameter bridge", "result normalization"],
            })
        accepted = rules.get("accepted_statuses")
        if isinstance(accepted, list) and accepted:
            status = self._status_of(target)
            checks.append({
                "level": 2,
                "level_name": self.LEVELS[2],
                "name": "status_matches_schema_contract",
                "status": status,
                "accepted_statuses": accepted,
                "passed": status in {str(x).lower() for x in accepted},
                "suggested_location": ["execution status contract", "result normalizer"],
            })
        # Generic agent result schema check: every result must have an id/name and status.
        for item in self._agent_results(context):
            checks.append({
                "level": 2,
                "level_name": self.LEVELS[2],
                "name": "participant_result_has_minimum_schema",
                "participant_id": item.get("participant_id"),
                "passed": bool(item.get("participant_id") or item.get("participant_name")) and bool(item.get("status")),
                "suggested_location": ["participant result schema", "delegation runtime result adapter"],
            })
        return checks

    def _level3_dependency(self, context: dict[str, Any], rules: dict[str, Any]) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []
        task_graph = context.get("task_graph") if isinstance(context.get("task_graph"), dict) else {}
        selected = [str(x).strip() for x in (task_graph.get("selected_participant_ids") or []) if str(x).strip()]
        result_ids = {str(item.get("participant_id") or "").strip() for item in self._agent_results(context)}
        if selected:
            missing = [pid for pid in selected if pid not in result_ids]
            checks.append({
                "level": 3,
                "level_name": self.LEVELS[3],
                "name": "selected_participants_have_results",
                "passed": not missing,
                "missing_participant_ids": missing,
                "suggested_location": ["TaskGraph generation", "participant mapping", "resume execution state"],
            })
        dependency_edges = task_graph.get("edges") or task_graph.get("dependencies") or []
        if isinstance(dependency_edges, list) and dependency_edges:
            known = set(selected) | result_ids | {str(p.get("participant_id") or p.get("id") or "") for p in task_graph.get("participants", []) if isinstance(p, dict)}
            missing_refs: list[dict[str, Any]] = []
            for edge in dependency_edges:
                if not isinstance(edge, dict):
                    continue
                src = str(edge.get("source") or edge.get("from") or edge.get("source_id") or "").strip()
                dst = str(edge.get("target") or edge.get("to") or edge.get("target_id") or "").strip()
                if src and src not in known:
                    missing_refs.append({"edge": edge, "missing": src})
                if dst and dst not in known:
                    missing_refs.append({"edge": edge, "missing": dst})
            checks.append({
                "level": 3,
                "level_name": self.LEVELS[3],
                "name": "dependency_edges_reference_existing_nodes",
                "passed": not missing_refs,
                "missing_refs": missing_refs[:20],
                "suggested_location": ["dependency graph builder", "task revision graph builder"],
            })
        return checks

    def _level4_capability(self, context: dict[str, Any], rules: dict[str, Any]) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []
        participants = self._participants(context)
        result_by_id = {str(item.get("participant_id") or "").strip(): item for item in self._agent_results(context)}
        for participant in participants:
            pid = str(participant.get("participant_id") or participant.get("id") or "").strip()
            profile = participant.get("capability_profile") if isinstance(participant.get("capability_profile"), dict) else {}
            capability_type = str(profile.get("capability_type") or participant.get("capability_type") or "").strip()
            tool_id = str(profile.get("tool_id") or profile.get("capability_id") or participant.get("tool_id") or "").strip()
            if not tool_id and capability_type != "runtime_registered_tool":
                continue
            result = result_by_id.get(pid, {})
            workflow_results = result.get("workflow_results") if isinstance(result.get("workflow_results"), dict) else {}
            evidence_text = self._stringify({"result": result, "workflow_results": workflow_results})
            status = self._status_of(workflow_results) or self._status_of(result)
            executed_as_tool = (
                str(workflow_results.get("capability_type") or "") == "runtime_registered_tool"
                or bool(workflow_results.get("tool_id"))
                or bool(workflow_results.get("tool_execution"))
                or "registered_tool" in evidence_text
            )
            checks.append({
                "level": 4,
                "level_name": self.LEVELS[4],
                "name": "bound_capability_must_execute_through_registered_path",
                "participant_id": pid,
                "tool_id": tool_id,
                "capability_type": capability_type,
                "status": status,
                "passed": executed_as_tool and status not in self.FAILURE_STATUSES,
                "suggested_location": ["agent capability binding", "registered tool dispatch", "execution lock"],
            })
        return checks

    def _level5_expectation(self, context: dict[str, Any], rules: dict[str, Any]) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []
        run_payload = context.get("run_payload") if isinstance(context.get("run_payload"), dict) else context
        final_answer = self._final_answer(run_payload)
        if rules.get("final_answer_required", True):
            checks.append({
                "level": 5,
                "level_name": self.LEVELS[5],
                "name": "final_answer_or_result_must_not_be_empty",
                "passed": bool(str(final_answer or "").strip()) or bool(self._agent_results(context)),
                "suggested_location": ["final synthesis", "participant result adapter", "output contract"],
            })
        forbidden_values = rules.get("forbidden_placeholder_values") or ["none", "null", "undefined", "nan"]
        if isinstance(final_answer, str) and final_answer.strip().casefold() in {str(v).casefold() for v in forbidden_values}:
            checks.append({
                "level": 5,
                "level_name": self.LEVELS[5],
                "name": "final_answer_must_not_be_placeholder_value",
                "passed": False,
                "value": final_answer,
                "suggested_location": ["result verification", "upstream participant output"],
            })
        return checks

    def _level6_side_effect(self, context: dict[str, Any], rules: dict[str, Any]) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []
        for item in self._agent_results(context):
            workflow_results = item.get("workflow_results") if isinstance(item.get("workflow_results"), dict) else {}
            text = self._stringify({"item": item, "workflow_results": workflow_results}).casefold()
            is_side_effect = bool(workflow_results.get("side_effect")) or bool(workflow_results.get("tool_id")) or "runtime_registered_tool" in text or "registered_tool" in text
            if not is_side_effect:
                continue
            status = self._status_of(workflow_results) or self._status_of(item)
            checks.append({
                "level": 6,
                "level_name": self.LEVELS[6],
                "name": "side_effect_capability_reports_success",
                "participant_id": item.get("participant_id"),
                "status": status,
                "passed": status in self.SUCCESS_STATUSES,
                "suggested_location": ["side-effect tool result", "capability return schema", "external operation verification"],
            })
            if _TEMPLATE_RE.search(text):
                checks.append({
                    "level": 6,
                    "level_name": self.LEVELS[6],
                    "name": "side_effect_input_output_must_not_contain_unresolved_template",
                    "participant_id": item.get("participant_id"),
                    "passed": False,
                    "suggested_location": ["side-effect preflight guard", "template resolution"],
                })
        return checks

    def _participants(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        direct = context.get("participants")
        if isinstance(direct, list):
            return [x for x in direct if isinstance(x, dict)]
        task_graph = context.get("task_graph") if isinstance(context.get("task_graph"), dict) else {}
        values = task_graph.get("participants") or task_graph.get("nodes") or []
        return [x for x in values if isinstance(x, dict)] if isinstance(values, list) else []

    def _agent_results(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        run_payload = context.get("run_payload") if isinstance(context.get("run_payload"), dict) else context
        values = run_payload.get("agent_results") if isinstance(run_payload.get("agent_results"), list) else []
        return [x for x in values if isinstance(x, dict)]

    def _status_of(self, value: Any) -> str:
        if isinstance(value, dict):
            return str(value.get("status") or value.get("result_status") or "").strip().lower()
        return ""

    def _final_answer(self, run_payload: dict[str, Any]) -> str:
        synthesis = run_payload.get("synthesis") if isinstance(run_payload.get("synthesis"), dict) else {}
        return str(synthesis.get("final_answer") or run_payload.get("final_answer") or "")

    def _stringify(self, output: Any) -> str:
        if isinstance(output, str):
            return output
        try:
            return json.dumps(output, ensure_ascii=False, default=str)
        except Exception:
            return str(output)
