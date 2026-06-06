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
        """Level 5 validates whether the result satisfies the stated runtime expectation.

        The implementation is deliberately generic:
        1. deterministic structural rules run first;
        2. if those rules cannot decide goal satisfaction, the verifier may
           escalate to LiteLLM through BrainModelRouter;
        3. model output is treated as an advisory verification check, not as
           execution evidence.
        """
        checks: list[dict[str, Any]] = []
        run_payload = context.get("run_payload") if isinstance(context.get("run_payload"), dict) else context
        task_graph = context.get("task_graph") if isinstance(context.get("task_graph"), dict) else {}
        final_answer = self._final_answer(run_payload)
        agent_results = self._agent_results(context)

        if rules.get("final_answer_required", True):
            checks.append({
                "level": 5,
                "level_name": self.LEVELS[5],
                "name": "final_answer_or_result_must_not_be_empty",
                "passed": bool(str(final_answer or "").strip()) or bool(agent_results),
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

        explicit_expectations = self._expectation_statements(context=context, rules=rules)
        if explicit_expectations:
            deterministic = self._deterministic_expectation_check(final_answer=final_answer, expectations=explicit_expectations, context=context)
            checks.append(deterministic)
            should_escalate = deterministic.get("passed") is None or bool(rules.get("force_llm_expectation_verification"))
        else:
            should_escalate = bool(rules.get("infer_expectation_with_llm", True)) and bool(final_answer or agent_results)

        if should_escalate and rules.get("enable_llm_expectation_verification", True):
            checks.append(self._llm_expectation_check(
                context=context,
                rules=rules,
                final_answer=final_answer,
                expectations=explicit_expectations,
                task_graph=task_graph,
            ))
        return checks

    def _expectation_statements(self, *, context: dict[str, Any], rules: dict[str, Any]) -> list[str]:
        values: list[str] = []
        for key in ("expectations", "expected_outcomes", "must_satisfy"):
            raw = rules.get(key)
            if isinstance(raw, str) and raw.strip():
                values.append(raw.strip())
            elif isinstance(raw, list):
                values.extend(str(x).strip() for x in raw if str(x).strip())
        task_graph = context.get("task_graph") if isinstance(context.get("task_graph"), dict) else {}
        for key in ("instruction", "raw_instruction", "task_instruction", "objective", "goal", "task_name"):
            value = task_graph.get(key)
            if isinstance(value, str) and value.strip():
                values.append(value.strip())
        run_payload = context.get("run_payload") if isinstance(context.get("run_payload"), dict) else {}
        for key in ("instruction", "objective", "goal", "task_name"):
            value = run_payload.get(key)
            if isinstance(value, str) and value.strip():
                values.append(value.strip())
        # Keep this compact. Evidence-heavy logs belong to evidence_engine, not
        # the model prompt.
        deduped: list[str] = []
        seen: set[str] = set()
        for value in values:
            clipped = value[:1200]
            marker = clipped.casefold()
            if marker not in seen:
                seen.add(marker)
                deduped.append(clipped)
        return deduped[:8]

    def _deterministic_expectation_check(self, *, final_answer: str, expectations: list[str], context: dict[str, Any]) -> dict[str, Any]:
        text = self._stringify({"final_answer": final_answer, "agent_results": self._agent_results(context)})
        if not str(final_answer or "").strip() and not self._agent_results(context):
            return {
                "level": 5,
                "level_name": self.LEVELS[5],
                "name": "declared_expectation_has_runtime_output",
                "passed": False,
                "expectations": expectations[:5],
                "suggested_location": ["final synthesis", "participant output", "result adapter"],
            }
        if _TEMPLATE_RE.search(text):
            return {
                "level": 5,
                "level_name": self.LEVELS[5],
                "name": "declared_expectation_output_must_be_materialized",
                "passed": False,
                "expectations": expectations[:5],
                "suggested_location": ["template resolution", "dependency mapping", "parameter hydration"],
            }
        # Generic deterministic rules cannot prove semantic goal satisfaction.
        # Return indeterminate so the optional LLM judge can be used.
        return {
            "level": 5,
            "level_name": self.LEVELS[5],
            "name": "declared_expectation_semantic_match_requires_judgment",
            "passed": None,
            "expectations": expectations[:5],
            "suggested_location": ["expectation verifier", "model orchestration"],
        }

    def _llm_expectation_check(
        self,
        *,
        context: dict[str, Any],
        rules: dict[str, Any],
        final_answer: str,
        expectations: list[str],
        task_graph: dict[str, Any],
    ) -> dict[str, Any]:
        prompt_payload = {
            "expectations": expectations[:8],
            "task_identity": {
                "task_name": task_graph.get("task_name") or task_graph.get("name") or "",
                "graph_id": task_graph.get("graph_id") or "",
            },
            "final_answer": final_answer[:2000],
            "participant_result_summaries": self._participant_result_summaries(context)[:12],
            "verification_rules": {
                "judge_only_goal_satisfaction": True,
                "do_not_infer_unseen_external_state": True,
                "return_json_only": True,
            },
        }
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a generic runtime verification judge. Decide whether the runtime output "
                    "satisfies the stated expectation using only the provided evidence. Do not assume "
                    "domain-specific facts. Return compact JSON with keys: passed, confidence, reason, "
                    "suggested_location. If evidence is insufficient, set passed to null."
                ),
            },
            {"role": "user", "content": json.dumps(prompt_payload, ensure_ascii=False, default=str)},
        ]
        complexity = str(rules.get("llm_expectation_complexity") or "critical")
        result = self.llm.complete_sync(
            brain="verification_brain",
            task_type="expectation_judgment",
            complexity=complexity,
            messages=messages,
            context={"verification_level": 5, "task_graph_id": task_graph.get("graph_id")},
            response_format={"type": "json_object"},
        )
        parsed = self._parse_llm_json(result.content)
        if result.status != "completed":
            return {
                "level": 5,
                "level_name": self.LEVELS[5],
                "name": "llm_expectation_judgment_unavailable",
                "passed": None,
                "llm_status": result.status,
                "error": result.error,
                "route": result.route,
                "suggested_location": ["brain model policy", "LiteLLM provider configuration"],
            }
        raw_passed = parsed.get("passed") if isinstance(parsed, dict) else None
        passed = raw_passed if isinstance(raw_passed, bool) else None
        return {
            "level": 5,
            "level_name": self.LEVELS[5],
            "name": "llm_expectation_judgment",
            "passed": passed,
            "confidence": parsed.get("confidence") if isinstance(parsed, dict) else None,
            "reason": str(parsed.get("reason") or "")[:800] if isinstance(parsed, dict) else "",
            "route": result.route,
            "suggested_location": parsed.get("suggested_location") if isinstance(parsed, dict) and isinstance(parsed.get("suggested_location"), list) else ["expectation", "result synthesis", "upstream output"],
        }

    def _participant_result_summaries(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for item in self._agent_results(context):
            workflow_results = item.get("workflow_results") if isinstance(item.get("workflow_results"), dict) else {}
            summaries.append({
                "participant_id": item.get("participant_id"),
                "participant_name": item.get("participant_name"),
                "status": item.get("status"),
                "final_answer": str(item.get("final_answer") or workflow_results.get("final_answer") or workflow_results.get("message") or "")[:1200],
                "tool_id": workflow_results.get("tool_id"),
                "capability_type": workflow_results.get("capability_type"),
            })
        return summaries

    def _parse_llm_json(self, content: str) -> dict[str, Any]:
        text = str(content or "").strip()
        if not text:
            return {}
        try:
            value = json.loads(text)
            return value if isinstance(value, dict) else {}
        except Exception:
            pass
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                value = json.loads(text[start:end + 1])
                return value if isinstance(value, dict) else {}
            except Exception:
                return {}
        return {}

    def _level6_side_effect(self, context: dict[str, Any], rules: dict[str, Any]) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []
        for item in self._agent_results(context):
            workflow_results = item.get("workflow_results") if isinstance(item.get("workflow_results"), dict) else {}
            evidence_text = self._stringify({"item": item, "workflow_results": workflow_results}).casefold()
            is_side_effect = (
                bool(workflow_results.get("side_effect"))
                or bool(workflow_results.get("tool_id"))
                or bool(workflow_results.get("delivery"))
                or bool(workflow_results.get("artifact_path"))
                or "runtime_registered_tool" in evidence_text
                or "registered_tool" in evidence_text
            )
            if not is_side_effect:
                continue
            status = self._status_of(workflow_results) or self._status_of(item)
            success_reported = status in self.SUCCESS_STATUSES
            checks.append({
                "level": 6,
                "level_name": self.LEVELS[6],
                "name": "side_effect_capability_reports_terminal_status",
                "participant_id": item.get("participant_id"),
                "participant_name": item.get("participant_name"),
                "status": status,
                "passed": success_reported,
                "side_effect_status": "accepted" if success_reported else "failed",
                "suggested_location": ["side-effect tool result", "capability return schema", "external operation verification"],
            })
            if _TEMPLATE_RE.search(evidence_text):
                checks.append({
                    "level": 6,
                    "level_name": self.LEVELS[6],
                    "name": "side_effect_input_output_must_not_contain_unresolved_template",
                    "participant_id": item.get("participant_id"),
                    "passed": False,
                    "side_effect_status": "failed",
                    "suggested_location": ["side-effect preflight guard", "template resolution"],
                })
                continue
            if not success_reported:
                continue
            checks.append(self._side_effect_verification_status(item=item, workflow_results=workflow_results))
        return checks

    def _side_effect_verification_status(self, *, item: dict[str, Any], workflow_results: dict[str, Any]) -> dict[str, Any]:
        verification = workflow_results.get("side_effect_verification") if isinstance(workflow_results.get("side_effect_verification"), dict) else {}
        mode = str(verification.get("mode") or workflow_results.get("side_effect_verification_mode") or "").strip().lower()
        status = str(verification.get("status") or verification.get("result_status") or "").strip().lower()
        artifact_refs = self._artifact_refs(workflow_results)
        if artifact_refs:
            missing = [ref for ref in artifact_refs if not self._local_ref_exists(ref)]
            return {
                "level": 6,
                "level_name": self.LEVELS[6],
                "name": "side_effect_local_artifact_must_exist",
                "participant_id": item.get("participant_id"),
                "participant_name": item.get("participant_name"),
                "verification_mode": "local_artifact",
                "passed": not missing,
                "side_effect_status": "verified" if not missing else "failed",
                "artifact_refs": artifact_refs[:20],
                "missing_artifact_refs": missing[:20],
                "suggested_location": ["artifact writer", "delivery recorder", "capability result schema"],
            }
        if mode in {"read_back", "callback", "status_check"}:
            verified = status in self.SUCCESS_STATUSES or bool(verification.get("verified"))
            return {
                "level": 6,
                "level_name": self.LEVELS[6],
                "name": "side_effect_read_back_verification",
                "participant_id": item.get("participant_id"),
                "participant_name": item.get("participant_name"),
                "verification_mode": mode,
                "passed": verified,
                "side_effect_status": "verified" if verified else "failed",
                "verification": verification,
                "suggested_location": ["read-back verifier", "capability verification adapter", "external state check"],
            }
        if mode in {"none", "not_verifiable"}:
            return {
                "level": 6,
                "level_name": self.LEVELS[6],
                "name": "side_effect_declared_not_verifiable",
                "participant_id": item.get("participant_id"),
                "participant_name": item.get("participant_name"),
                "verification_mode": mode,
                "passed": None,
                "side_effect_status": "not_verifiable",
                "requires_user_confirmation": True,
                "suggested_location": ["capability side-effect declaration", "user confirmation channel"],
            }
        return {
            "level": 6,
            "level_name": self.LEVELS[6],
            "name": "side_effect_accepted_pending_user_confirmation",
            "participant_id": item.get("participant_id"),
            "participant_name": item.get("participant_name"),
            "tool_id": workflow_results.get("tool_id"),
            "verification_mode": mode or "accepted_only",
            "passed": None,
            "side_effect_status": "accepted_pending_user_confirmation",
            "requires_user_confirmation": True,
            "default_assumption": "success_until_user_reports_failure",
            "suggested_location": ["capability side-effect declaration", "optional read-back verifier", "user confirmation channel"],
        }

    def _artifact_refs(self, workflow_results: dict[str, Any]) -> list[str]:
        refs: list[str] = []
        for key in ("artifact_path", "file_path", "output_path", "delivery_path", "path"):
            value = workflow_results.get(key)
            if isinstance(value, str) and value.strip():
                refs.append(value.strip())
        raw = workflow_results.get("artifacts")
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, str) and item.strip():
                    refs.append(item.strip())
                elif isinstance(item, dict):
                    for key in ("path", "file_path", "artifact_path"):
                        value = item.get(key)
                        if isinstance(value, str) and value.strip():
                            refs.append(value.strip())
        deduped: list[str] = []
        seen: set[str] = set()
        for ref in refs:
            if ref not in seen:
                seen.add(ref)
                deduped.append(ref)
        return deduped

    def _local_ref_exists(self, ref: str) -> bool:
        from pathlib import Path
        path = Path(ref)
        if not path.is_absolute():
            path = Path.cwd() / path
        try:
            return path.exists() and (path.is_file() or path.is_dir())
        except Exception:
            return False

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
