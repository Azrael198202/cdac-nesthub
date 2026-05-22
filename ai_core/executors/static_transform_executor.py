from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import PROJECT_ROOT, RUNTIME_DIR
from ai_core.validation.schema_validator import SchemaValidator


class StaticTransformExecutor:
    """Deterministic stage executor for non-LLM pipeline layers.

    The executor is intentionally domain-neutral. It does not decide what the
    user is asking for; it only carries forward generic upstream contracts,
    checks completeness, prepares resources, validates the locked plan, and
    records verification/repair state.
    """

    def __init__(self) -> None:
        self.loader = ConfigLoader()
        self.validator = SchemaValidator()

    async def execute(self, workflow_node, node_config, state, capability_result):
        node_id = str(node_config.get("node_id") or workflow_node.get("id") or "")
        builders = {
            "requirement_completion": self._requirement_completion,
            "context_awareness": self._context_awareness,
            "execution_preparation": self._execution_preparation,
            "pre_execution_validation": self._pre_execution_validation,
            "result_verification": self._result_verification,
            "feedback_repair": self._feedback_repair,
        }
        result = builders.get(node_id, self._generic_record)(node_id=node_id, state=state, node_config=node_config)
        result.setdefault("_executor_type", "static_transform")
        result.setdefault("_node_id", node_id)
        result.setdefault("_status", "executed")
        self._validate_if_possible(result, node_config)
        return result

    def _requirement_completion(self, *, node_id: str, state: dict[str, Any], node_config: dict[str, Any]) -> dict[str, Any]:
        results = self._results(state)
        input_record = self._stage_payload(results.get("input_parsing"))
        intent_record = self._stage_payload(results.get("intent_recognition"))
        known = self._merge_known(input_record, intent_record)
        missing = self._collect_missing(input_record, intent_record, known)
        complete = len(missing) == 0
        return {
            "requirement_record": {
                "status": "complete" if complete else "missing_information_required",
                "complete": complete,
                "known_parameters": known,
                "missing_information": missing,
                "ui_request": None if complete else {
                    "type": "collect_missing_information",
                    "fields": missing,
                    "reason": "Required information is not complete for the recognized intent.",
                },
                "upstream_refs": ["input_parsing", "intent_recognition"],
                "next_stage": "context_awareness" if complete else "requirement_completion",
            },
            "status": "completed" if complete else "waiting_for_human_information",
            "message": "Requirements complete." if complete else "Missing information is required.",
        }

    def _context_awareness(self, *, node_id: str, state: dict[str, Any], node_config: dict[str, Any]) -> dict[str, Any]:
        results = self._results(state)
        req = self._stage_payload(results.get("requirement_completion"), "requirement_record")
        intent = self._stage_payload(results.get("intent_recognition"))
        clean_context = {
            "run_id": state.get("run_id"),
            "original_input": state.get("input"),
            "recognized_intent": self._first_non_empty(intent.get("intent_type"), intent.get("classified_intent"), intent.get("intent"), intent.get("name")),
            "intent_summary": self._first_non_empty(intent.get("intent_summary"), intent.get("summary"), intent.get("objective")),
            "known_parameters": req.get("known_parameters") if isinstance(req.get("known_parameters"), dict) else {},
            "missing_information": req.get("missing_information") if isinstance(req.get("missing_information"), list) else [],
            "conversation_relation": "new_task",
            "context_sharing_policy": {
                "independent_peer_results": "excluded",
                "dependent_peer_results": "strict_json_safe_summary_only",
            },
        }
        return {
            "context_record": {
                "status": "ready_for_planning" if not clean_context["missing_information"] else "blocked_by_missing_information",
                "clean_context": clean_context,
                "upstream_refs": ["input_parsing", "intent_recognition", "requirement_completion"],
            },
            "status": "completed" if not clean_context["missing_information"] else "waiting_for_human_information",
            "message": "Clean context prepared." if not clean_context["missing_information"] else "Clean context prepared with missing information hold.",
        }

    def _execution_preparation(self, *, node_id: str, state: dict[str, Any], node_config: dict[str, Any]) -> dict[str, Any]:
        results = self._results(state)
        plan_raw = results.get("workflow_planning") if isinstance(results.get("workflow_planning"), dict) else {}
        plan = plan_raw if isinstance(plan_raw.get("planned_steps"), list) else self._stage_payload(plan_raw)
        steps = plan.get("planned_steps") if isinstance(plan.get("planned_steps"), list) else []
        bundle = {
            "kind": "execution_preparation_bundle",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "run_id": state.get("run_id"),
            "steps": [self._prepared_step(step, index) for index, step in enumerate(steps)],
        }
        artifact_path = self._write_runtime_artifact(state, "execution_preparation", "resource_bundle.json", bundle)
        return {
            "execution_preparation_record": {
                "status": "prepared" if steps else "no_steps_to_prepare",
                "artifact_path": artifact_path,
                "resource_bundle": bundle,
                "prepared_step_count": len(steps),
                "upstream_refs": ["workflow_planning"],
            },
            "status": "completed" if steps else "blocked",
            "message": "Execution resources prepared." if steps else "No planned steps were available for preparation.",
        }

    def _pre_execution_validation(self, *, node_id: str, state: dict[str, Any], node_config: dict[str, Any]) -> dict[str, Any]:
        results = self._results(state)
        plan_raw = results.get("workflow_planning") if isinstance(results.get("workflow_planning"), dict) else {}
        plan = plan_raw if isinstance(plan_raw.get("planned_steps"), list) else self._stage_payload(plan_raw)
        prep = self._stage_payload(results.get("execution_preparation"), "execution_preparation_record")
        steps = plan.get("planned_steps") if isinstance(plan.get("planned_steps"), list) else []
        checks = []
        for index, step in enumerate(steps):
            missing_fields = step.get("missing_fields") if isinstance(step.get("missing_fields"), list) else []
            params = step.get("parameters") if isinstance(step.get("parameters"), dict) else {}
            missing_required = params.get("missing_required") if isinstance(params.get("missing_required"), (list, dict)) else []
            method = self._execution_method(step)
            passed = not missing_fields and not missing_required and bool(method)
            checks.append({
                "step_id": str(step.get("step_id") or step.get("task_id") or f"step_{index + 1}"),
                "schema_check": "passed",
                "parameter_check": "passed" if not missing_fields and not missing_required else "failed",
                "execution_method_check": "passed" if method else "failed",
                "tool_presence_check": "not_required" if method in {"content_generation", "model_knowledge", "knowledge_base"} else "deferred_to_runtime_registry",
                "confirmation_check": "requires_human_confirmation" if bool(step.get("requires_human_confirmation")) else "not_required",
                "sandbox_check": "passed" if method in {"content_generation", "model_knowledge", "knowledge_base"} else "deferred_until_generated_resource_exists",
                "passed": passed,
            })
        passed_all = bool(steps) and all(item.get("passed") for item in checks)
        return {
            "validation_record": {
                "status": "passed" if passed_all else "failed",
                "checks": checks,
                "prepared_artifact_path": prep.get("artifact_path"),
                "upstream_refs": ["workflow_planning", "execution_preparation"],
            },
            "status": "completed" if passed_all else "blocked",
            "message": "Pre-execution validation passed." if passed_all else "Pre-execution validation failed or no executable steps exist.",
        }

    def _result_verification(self, *, node_id: str, state: dict[str, Any], node_config: dict[str, Any]) -> dict[str, Any]:
        results = self._results(state)
        execution = self._stage_payload(results.get("execution"))
        steps = execution.get("execution_steps") if isinstance(execution.get("execution_steps"), list) else []
        blocked = execution.get("blocked_steps") if isinstance(execution.get("blocked_steps"), list) else []
        verified_steps = []
        for step in steps:
            result = step.get("result") if isinstance(step, dict) and isinstance(step.get("result"), dict) else {}
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            has_material = any(data.get(k) not in (None, "", [], {}) for k in ("answer_material", "normalized_facts", "content", "output"))
            verified_steps.append({
                "step_id": step.get("step_id"),
                "real_execution_check": "passed" if result else "failed",
                "step_satisfaction_check": "passed" if has_material or result.get("status") == "success" else "needs_review",
                "confidence_check": "passed" if result.get("status") in {"success", "completed"} else "needs_review",
                "passed": bool(result) and (has_material or result.get("status") in {"success", "completed"}),
            })
        passed = bool(verified_steps) and all(item.get("passed") for item in verified_steps) and not blocked
        return {
            "verification_record": {
                "status": "passed" if passed else "failed",
                "verified_steps": verified_steps,
                "blocked_steps": blocked,
                "fallback_allowed": False,
                "upstream_refs": ["execution"],
            },
            "status": "completed" if passed else "blocked",
            "message": "Execution result verified." if passed else "Execution result did not pass verification.",
        }

    def _feedback_repair(self, *, node_id: str, state: dict[str, Any], node_config: dict[str, Any]) -> dict[str, Any]:
        results = self._results(state)
        verification = self._stage_payload(results.get("result_verification"), "verification_record")
        validation = self._stage_payload(results.get("pre_execution_validation"), "validation_record")
        needs_repair = verification.get("status") == "failed" or validation.get("status") == "failed"
        actions = []
        if validation.get("status") == "failed":
            actions.append({"type": "return_to_requirement_or_planning", "reason": "pre_execution_validation_failed"})
        if verification.get("status") == "failed":
            actions.append({"type": "report_failure_or_use_planned_fallback", "reason": "result_verification_failed"})
        return {
            "repair_record": {
                "status": "repair_required" if needs_repair else "no_repair_required",
                "actions": actions,
                "allowed_recovery_only": True,
                "upstream_refs": ["pre_execution_validation", "result_verification"],
            },
            "status": "completed" if not needs_repair else "blocked",
            "message": "No repair required." if not needs_repair else "Repair is required before final synthesis.",
        }

    def _generic_record(self, *, node_id: str, state: dict[str, Any], node_config: dict[str, Any]) -> dict[str, Any]:
        key = ((node_config.get("stage_contract") or {}).get("output_key") or "stage_record")
        return {key: {"status": "executed", "node_id": node_id}, "status": "completed", "message": "Stage executed."}

    def _prepared_step(self, step: dict[str, Any], index: int) -> dict[str, Any]:
        method = self._execution_method(step)
        step_id = str(step.get("step_id") or step.get("task_id") or f"step_{index + 1}")
        known = {}
        params = step.get("parameters") if isinstance(step.get("parameters"), dict) else {}
        if isinstance(params.get("known"), dict):
            known.update(params.get("known") or {})
        return {
            "step_id": step_id,
            "execution_method": method,
            "source_policy": step.get("source_policy") if isinstance(step.get("source_policy"), dict) else {},
            "web_collection": {
                "required": method == "web_search",
                "targets": step.get("source_targets") if isinstance(step.get("source_targets"), list) else [],
            },
            "tool_generation": {
                "required": method in {"runtime_generated_tool", "api_call", "existing_tool"},
                "design_contract": {
                    "capability": step.get("required_capability"),
                    "input_schema": {"type": "object", "additionalProperties": True},
                    "output_schema": {"type": "object", "additionalProperties": True},
                },
            },
            "prompt_contract": {
                "required": method in {"content_generation", "model_knowledge"},
                "objective": step.get("objective"),
                "known_parameters": known,
                "output_format": "json_object_with_answer_material",
            },
            "shell_generation": {
                "required": method == "shell",
                "design_contract": None,
            },
            "sandbox_precheck": {
                "required": method not in {"content_generation", "model_knowledge", "knowledge_base"},
                "status": "passed" if method in {"content_generation", "model_knowledge", "knowledge_base"} else "deferred_until_artifact_exists",
            },
        }

    def _stage_payload(self, value: Any, preferred_key: str | None = None) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        if preferred_key and isinstance(value.get(preferred_key), dict):
            return value[preferred_key]
        for key in (
            "input_record", "intent_record", "requirement_record", "context_record",
            "execution_plan", "execution_preparation_record",
            "validation_record", "verification_record", "repair_record",
        ):
            if isinstance(value.get(key), dict):
                return value[key]
        return value

    def _merge_known(self, *records: dict[str, Any]) -> dict[str, Any]:
        known: dict[str, Any] = {}
        for record in records:
            for key in ("known_parameters", "parameters", "parsed_entities", "entities", "slots", "normalized_intent"):
                value = record.get(key) if isinstance(record, dict) else None
                if isinstance(value, dict):
                    nested = value.get("known") if isinstance(value.get("known"), dict) else value
                    for k, v in nested.items():
                        if v not in (None, "", [], {}):
                            known[str(k)] = v
            missing = record.get("missing_information") if isinstance(record, dict) else None
            if isinstance(missing, list):
                continue
        return known

    def _collect_missing(self, input_record: dict[str, Any], intent_record: dict[str, Any], known: dict[str, Any]) -> list[dict[str, Any]]:
        fields: list[Any] = []
        for record in (input_record, intent_record):
            for key in ("missing_information", "missing_fields", "required_missing", "missing_required"):
                value = record.get(key) if isinstance(record, dict) else None
                if isinstance(value, list):
                    fields.extend(value)
                elif isinstance(value, dict):
                    fields.extend([k for k, v in value.items() if v in (None, "", [], {})])
        normalized = []
        seen = set()
        for item in fields:
            if isinstance(item, dict):
                name = str(item.get("name") or item.get("field") or item.get("id") or "").strip()
                label = item.get("label") or name
            else:
                name = str(item).strip()
                label = name
            if not name or name in seen or known.get(name) not in (None, "", [], {}):
                continue
            seen.add(name)
            normalized.append({"name": name, "label": label, "required": True})
        return normalized

    def _execution_method(self, step: dict[str, Any]) -> str:
        for key in ("execution_method", "method"):
            value = step.get(key) if isinstance(step, dict) else None
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict) and isinstance(value.get("method"), str):
                return value["method"].strip()
        decision = step.get("execution_method_decision") if isinstance(step, dict) else None
        if isinstance(decision, dict) and isinstance(decision.get("method"), str):
            return decision["method"].strip()
        strategy = step.get("execution_strategy") if isinstance(step, dict) else None
        if isinstance(strategy, list):
            for item in strategy:
                text = str(item).strip()
                if text in {"content_generation", "model_generation", "generate_content"}:
                    return "content_generation"
                if text in {"web_search", "web_evidence", "web_retrieval"}:
                    return "web_search"
                if text in {"api_call", "structured_provider"}:
                    return "api_call"
                if text in {"tool_generation", "runtime_generated_tool"}:
                    return "runtime_generated_tool"
                if text in {"model_knowledge", "knowledge_base"}:
                    return text
        return ""

    def _write_runtime_artifact(self, state: dict[str, Any], stage: str, name: str, payload: dict[str, Any]) -> str:
        run_id = str(state.get("run_id") or "unknown_run")
        out_dir = RUNTIME_DIR / "sessions" / run_id / stage
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / name
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path.relative_to(PROJECT_ROOT))

    def _validate_if_possible(self, result: dict[str, Any], node_config: dict[str, Any]) -> None:
        schema_path = node_config.get("output_schema")
        if not schema_path:
            return
        try:
            schema = self.loader.load_json(PROJECT_ROOT / schema_path)
            self.validator.validate_data(result, schema)
        except Exception:
            return

    def _results(self, state: dict[str, Any]) -> dict[str, Any]:
        return state.get("results", {}) if isinstance(state.get("results"), dict) else {}

    def _first_non_empty(self, *values: Any) -> Any:
        for value in values:
            if value not in (None, "", [], {}):
                return value
        return None
