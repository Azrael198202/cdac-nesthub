from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from verification_brain.settings import VerificationBrainSettingsStore
from verification_brain.runtime_validator import RuntimeSerializationValidator


@dataclass
class ModelVerificationLoopConfig:
    enabled: bool = True
    max_attempts: int = 3
    critical_stages: set[str] = field(default_factory=lambda: {
        "intent_recognition",
        "workflow_planning",
        "agent_action_planning",
        "result_verification",
        "final_synthesis",
        "presentation",
        "presentation_brain",
    })


class ConvergenceController:
    """Evaluate whether the verification/repair loop can move forward.

    The controller is metric-driven and stage-contract driven.  It does not use
    task names, tool names, domain words, or scenario-specific decisions.
    """

    def assess(self, *, judgment: dict[str, Any], settings: Any, history: list[dict[str, Any]]) -> dict[str, Any]:
        passed = bool(judgment.get("passed") is True)
        confidence = self._ratio(judgment.get("confidence"), default=1.0 if passed else 0.0)
        quality = self._ratio(judgment.get("quality"), default=confidence)
        consensus = self._ratio(judgment.get("consensus"), default=confidence)
        meta_ok = bool(judgment.get("meta_verified", True))
        accepted = (
            passed
            and confidence >= float(settings.minimum_confidence)
            and quality >= float(settings.minimum_quality)
            and consensus >= float(settings.minimum_consensus)
            and (meta_ok or not bool(settings.require_meta_verification))
        )
        best_quality = max([self._ratio(item.get("quality"), self._ratio(item.get("confidence"), 0.0)) for item in history] + [0.0])
        trend = "improving" if quality >= best_quality else "regressing"
        return {
            "accepted": accepted,
            "quality": quality,
            "confidence": confidence,
            "consensus": consensus,
            "meta_verified": meta_ok,
            "trend": trend,
            "thresholds": {
                "minimum_quality": settings.minimum_quality,
                "minimum_confidence": settings.minimum_confidence,
                "minimum_consensus": settings.minimum_consensus,
            },
        }

    @staticmethod
    def _ratio(value: Any, default: float) -> float:
        try:
            parsed = float(value)
        except Exception:
            parsed = default
        return max(0.0, min(parsed, 1.0))


class ModelVerificationLoop:
    """Verification-brain driven self-repair loop for model stages.

    The loop is a gateway between model generation and the next runtime layer:
    generate -> criticize -> meta-verify criticism -> repair -> converge.
    Failure is returned only when the configured verifier/repair loop cannot
    reach the declared stage contract.  All checks are generic: contract,
    schema, evidence, consistency, confidence, and convergence.
    """

    def __init__(self, config: ModelVerificationLoopConfig | None = None) -> None:
        self.config = config or ModelVerificationLoopConfig()
        self.settings_store = VerificationBrainSettingsStore()
        self.convergence = ConvergenceController()
        self.runtime_validator = RuntimeSerializationValidator()

    def runtime_settings(self) -> Any:
        return self.settings_store.load()

    def should_verify(self, *, node_id: str | None, adapter: dict[str, Any] | None = None) -> bool:
        settings = self.runtime_settings()
        if not self.config.enabled or not settings.enabled or not settings.verify_model_stages:
            return False
        node = str(node_id or "").strip()
        adapter = adapter if isinstance(adapter, dict) else {}
        if adapter.get("disable_model_verification_loop") is True:
            return False
        if str(node).startswith("verification_brain::") or "::verification_repair" in str(node):
            return False
        if adapter.get("enable_model_verification_loop") is True:
            return True
        if settings.verify_all_model_stages:
            return True
        return node in set(settings.stage_scope or self.config.critical_stages)

    def block_stage_on_failure(self) -> bool:
        return bool(self.runtime_settings().block_stage_on_failure)

    async def verify_and_repair(
        self,
        *,
        node_id: str,
        state: dict[str, Any],
        candidate: dict[str, Any],
        adapter: dict[str, Any],
        prompt: dict[str, Any],
        rendered_user_prompt: str,
        schema: dict[str, Any],
        router: Any,
        event_bus: Any,
        run_id: str,
        validator: Any | None = None,
        recorder: Any | None = None,
    ) -> dict[str, Any]:
        if not self.should_verify(node_id=node_id, adapter=adapter):
            return candidate

        settings = self.runtime_settings()
        current = candidate if isinstance(candidate, dict) else {"value": candidate}
        runtime_validation = self.runtime_validator.validate_and_repair(current)
        if runtime_validation.repaired:
            current = runtime_validation.value if isinstance(runtime_validation.value, dict) else {"value": runtime_validation.value}
            await event_bus.emit(run_id, {
                "type": "RUNTIME_SERIALIZATION_REPAIRED",
                "title": "Runtime serialization repaired",
                "message": runtime_validation.error or "Runtime payload was converted to a JSON-safe form.",
                "node_id": node_id,
                "findings": runtime_validation.findings,
            })
        elif not runtime_validation.passed:
            current = {
                "status": "failed",
                "failure_class": "runtime_serialization_problem",
                "message": runtime_validation.error or "Runtime payload is not serializable.",
                "findings": runtime_validation.findings,
            }
        attempts: list[dict[str, Any]] = []
        max_rounds = self._positive_int(adapter.get("model_verification_max_attempts"), settings.max_repair_rounds)

        for attempt_index in range(max_rounds + 1):
            judgment = await self._judge(
                node_id=node_id,
                state=state,
                candidate=current,
                adapter=adapter,
                router=router,
                run_id=run_id,
                attempt_index=attempt_index,
                settings=settings,
            )
            if settings.require_meta_verification:
                judgment = await self._meta_verify_judgment(
                    node_id=node_id,
                    state=state,
                    candidate=current,
                    judgment=judgment,
                    adapter=adapter,
                    router=router,
                    run_id=run_id,
                    attempt_index=attempt_index,
                )
            convergence = self.convergence.assess(judgment=judgment, settings=settings, history=attempts)
            judgment["convergence"] = convergence
            judgment.setdefault("quality", convergence.get("quality"))
            judgment.setdefault("consensus", convergence.get("consensus"))
            attempts.append(judgment)
            await event_bus.emit(run_id, {
                "type": "MODEL_VERIFICATION_JUDGMENT",
                "title": "Model verification judgment",
                "message": f"node={node_id}, accepted={convergence.get('accepted')}, attempt={attempt_index}",
                "node_id": node_id,
                "attempt_index": attempt_index,
                "judgment": judgment,
                "convergence": convergence,
            })
            if convergence.get("accepted") is True:
                current.setdefault("_model_verification", {})
                current["_model_verification"].update({
                    "status": "passed",
                    "attempts": attempts,
                    "convergence": convergence,
                })
                return current
            if attempt_index >= max_rounds:
                break
            correction_prompt = self._correction_prompt(judgment)
            if not correction_prompt:
                break
            regenerated = await self._regenerate(
                node_id=node_id,
                state=state,
                current=current,
                correction_prompt=correction_prompt,
                adapter=adapter,
                prompt=prompt,
                rendered_user_prompt=rendered_user_prompt,
                schema=schema,
                router=router,
                run_id=run_id,
                attempt_index=attempt_index + 1,
            )
            if isinstance(regenerated, dict):
                runtime_validation = self.runtime_validator.validate_and_repair(regenerated)
                if runtime_validation.repaired:
                    regenerated = runtime_validation.value if isinstance(runtime_validation.value, dict) else {"value": runtime_validation.value}
                    await event_bus.emit(run_id, {
                        "type": "RUNTIME_SERIALIZATION_REPAIRED",
                        "title": "Runtime serialization repaired after regeneration",
                        "message": runtime_validation.error or "Regenerated payload was converted to a JSON-safe form.",
                        "node_id": node_id,
                        "attempt_index": attempt_index + 1,
                        "findings": runtime_validation.findings,
                    })
                if validator is not None:
                    try:
                        validator.validate_data(regenerated, schema)
                    except Exception as exc:
                        regenerated.setdefault("_model_verification_schema_error", str(exc))
                        await event_bus.emit(run_id, {
                            "type": "MODEL_VERIFICATION_REPAIR_SCHEMA_WARNING",
                            "title": "Regenerated output failed schema validation",
                            "message": str(exc),
                            "node_id": node_id,
                            "attempt_index": attempt_index + 1,
                        })
                if recorder is not None:
                    try:
                        path = recorder.record(
                            run_id=run_id,
                            node_id=node_id,
                            phase=f"model_verification_repair_{attempt_index + 1}",
                            payload={
                                "node_id": node_id,
                                "attempt_index": attempt_index + 1,
                                "judgment": judgment,
                                "result": regenerated,
                            },
                        )
                        regenerated["_model_verification_repair_trace_path"] = str(path)
                    except Exception:
                        pass
                current = regenerated

        current.setdefault("_model_verification", {})
        current["_model_verification"].update({
            "status": "failed",
            "attempts": attempts,
            "last_judgment": attempts[-1] if attempts else {},
            "requires_repair": True,
            "exhausted": True,
        })
        return current

    async def _judge(self, *, node_id: str, state: dict[str, Any], candidate: dict[str, Any], adapter: dict[str, Any], router: Any, run_id: str, attempt_index: int, settings: Any) -> dict[str, Any]:
        payload = {
            "stage_id": node_id,
            "stage_responsibility": self._stage_responsibility(node_id),
            "user_request": str(state.get("input") or "")[:2000],
            "previous_results_summary": self._compact_previous_results(state.get("results")),
            "candidate_output": candidate,
            "verification_policy": settings.to_dict() if hasattr(settings, "to_dict") else {},
            "verification_rules": {
                "judge_stage_contract_only": True,
                "separate_execution_parameters_from_semantic_facts": True,
                "do_not_accept_unresolved_templates": True,
                "do_not_accept_material_not_supported_by_available_evidence": True,
                "if_external_material_is_required_check_evidence_flow": True,
                "return_actionable_correction_prompt_when_failed": True,
                "explain_why_each_required_change_is_necessary": True,
            },
        }
        verifier_prompt = {
            "id": "verification_brain_model_loop_judge",
            "system": (
                "You are verification_brain. Verify a generated runtime stage output against the stage responsibility, "
                "schema intent, available context, and evidence constraints. Do not add domain facts. "
                "If you find a defect, explain why it is a real defect and provide a minimal correction prompt. "
                "Return JSON only with keys: passed, confidence, quality, consensus, reason, failed_contracts, "
                "required_changes, correction_prompt. If uncertain, passed must be false."
            ),
        }
        verifier_adapter = self._verification_adapter(adapter, suffix="judge")
        try:
            result = await router.generate_json(
                run_id=run_id,
                node_id=f"verification_brain::{node_id}",
                adapter=verifier_adapter,
                prompt=verifier_prompt,
                rendered_user_prompt=json.dumps(payload, ensure_ascii=False, default=str),
                schema=self._judgment_schema(),
            )
            if isinstance(result, dict):
                result.setdefault("attempt_index", attempt_index)
                result.setdefault("verified_stage_id", node_id)
                normalized = self._normalize_judgment(result)
                return self._apply_stage_aware_judgment_guard(
                    node_id=node_id,
                    candidate=candidate,
                    judgment=normalized,
                    attempt_index=attempt_index,
                )
        except Exception as exc:
            return self._normalize_judgment({
                "passed": False,
                "confidence": 0,
                "quality": 0,
                "consensus": 0,
                "reason": f"verification model unavailable: {exc}",
                "failed_contracts": ["verification_model_unavailable"],
                "required_changes": ["Regenerate with stricter adherence to the stage contract."],
                "correction_prompt": "Regenerate the stage output. Keep only fields supported by the input contract and prior verified results. Do not invent missing facts.",
                "attempt_index": attempt_index,
                "verified_stage_id": node_id,
            })
        return self._normalize_judgment({
            "passed": False,
            "confidence": 0,
            "quality": 0,
            "consensus": 0,
            "reason": "verification model returned no usable judgment",
            "failed_contracts": ["empty_verification_judgment"],
            "required_changes": ["Return a stage result that satisfies the explicit stage contract."],
            "correction_prompt": "Regenerate the stage output according to the explicit stage contract and available evidence only.",
            "attempt_index": attempt_index,
            "verified_stage_id": node_id,
        })

    async def _meta_verify_judgment(self, *, node_id: str, state: dict[str, Any], candidate: dict[str, Any], judgment: dict[str, Any], adapter: dict[str, Any], router: Any, run_id: str, attempt_index: int) -> dict[str, Any]:
        payload = {
            "stage_id": node_id,
            "stage_responsibility": self._stage_responsibility(node_id),
            "candidate_output": candidate,
            "critic_judgment": judgment,
            "meta_rules": {
                "accept_only_actionable_and_contract_based_criticism": True,
                "reject_business_or_domain_assumptions_not_present_in_context": True,
                "reject_changes_that_expand_scope": True,
                "confirm_failure_reason_before_repair": True,
            },
        }
        prompt = {
            "id": "verification_brain_meta_verifier",
            "system": (
                "You are the meta verifier inside verification_brain. Judge whether the critic judgment is reasonable, "
                "contract-based, and useful for repair. Do not judge external facts. Return JSON only."
            ),
        }
        try:
            result = await router.generate_json(
                run_id=run_id,
                node_id=f"verification_brain::meta::{node_id}",
                adapter=self._verification_adapter(adapter, suffix="meta"),
                prompt=prompt,
                rendered_user_prompt=json.dumps(payload, ensure_ascii=False, default=str),
                schema=self._meta_schema(),
            )
            if isinstance(result, dict):
                updated = self._apply_meta_context_guard(
                    node_id=node_id,
                    candidate=candidate,
                    judgment=judgment,
                    meta_result=result,
                    attempt_index=attempt_index,
                )
                return self._normalize_judgment(updated)
        except Exception as exc:
            updated = dict(judgment)
            updated["meta_verified"] = False
            updated["meta_reason"] = f"meta verification unavailable: {exc}"
            updated["passed"] = False
            return self._normalize_judgment(updated)
        updated = dict(judgment)
        updated["meta_verified"] = False
        updated["meta_reason"] = "meta verifier returned no usable judgment"
        updated["passed"] = False
        return self._normalize_judgment(updated)

    def _apply_stage_aware_judgment_guard(self, *, node_id: str, candidate: dict[str, Any], judgment: dict[str, Any], attempt_index: int) -> dict[str, Any]:
        """Keep verification aligned with the current layer responsibility.

        The model critic is useful, but it must not evaluate a planning layer as
        if it were the execution layer.  This guard is deterministic and generic:
        it compares the criticism with the declared stage role and the actual
        candidate shape.  It does not contain task, provider, or domain words.
        """
        local = self._local_stage_contract_judgment(node_id=node_id, candidate=candidate, attempt_index=attempt_index)
        if bool(judgment.get("passed") is True):
            if not local.get("passed"):
                return local
            judgment.setdefault("stage_contract_guard", {"status": "aligned", "local_passed": True})
            return judgment

        text = self._judgment_text(judgment)
        if self._criticism_crosses_layer_boundary(node_id=node_id, text=text):
            guarded = dict(local)
            guarded["stage_contract_guard"] = {
                "status": "critic_rejected",
                "reason": "critic requested work outside the verified stage responsibility",
                "critic_reason": str(judgment.get("reason") or "")[:1200],
            }
            if local.get("passed"):
                return guarded
            guarded["reason"] = local.get("reason") or "Stage output failed local contract validation."
            return guarded
        if local.get("passed") and self._candidate_has_required_stage_signal(node_id=node_id, candidate=candidate):
            guarded = dict(local)
            guarded["stage_contract_guard"] = {
                "status": "critic_rejected",
                "reason": "candidate satisfies the deterministic stage contract; critic failed to bind to the stage role",
                "critic_reason": str(judgment.get("reason") or "")[:1200],
            }
            return guarded
        judgment.setdefault("stage_contract_guard", {"status": "critic_accepted", "local_passed": bool(local.get("passed"))})
        return judgment

    def _apply_meta_context_guard(self, *, node_id: str, candidate: dict[str, Any], judgment: dict[str, Any], meta_result: dict[str, Any], attempt_index: int) -> dict[str, Any]:
        accepted = bool(meta_result.get("accepted") is True)
        reason = str(meta_result.get("reason") or "")
        replacement = str(meta_result.get("replacement_correction_prompt") or "").strip()
        updated = dict(judgment)
        local = self._local_stage_contract_judgment(node_id=node_id, candidate=candidate, attempt_index=attempt_index)
        meta_text = "\n".join([reason, replacement])
        if accepted and self._meta_references_absent_context(candidate=candidate, text=meta_text):
            accepted = False
            reason = (reason + "\nMeta context guard rejected the judgment because it refers to fields or sections not present in the candidate output.").strip()
        if accepted and self._criticism_crosses_layer_boundary(node_id=node_id, text=self._judgment_text(judgment) + "\n" + meta_text):
            accepted = False
            reason = (reason + "\nMeta context guard rejected the judgment because the accepted repair would move work into the wrong layer.").strip()
        if not accepted and local.get("passed"):
            updated.update(local)
            updated["meta_verified"] = True
            updated["meta_reason"] = reason or "Meta verifier rejected the critic; deterministic stage contract passed."
            updated["meta_context_guard"] = {"status": "critic_rejected_local_contract_passed"}
            updated["attempt_index"] = attempt_index
            return updated
        updated["meta_verified"] = accepted
        updated["meta_reason"] = reason
        if not accepted:
            updated["passed"] = False
            updated["confidence"] = min(float(updated.get("confidence") or 0), 0.49)
            if replacement and not self._criticism_crosses_layer_boundary(node_id=node_id, text=replacement):
                updated["correction_prompt"] = replacement
        updated["attempt_index"] = attempt_index
        return updated

    def _local_stage_contract_judgment(self, *, node_id: str, candidate: dict[str, Any], attempt_index: int) -> dict[str, Any]:
        stage = str(node_id or "").strip()
        data = candidate.get("data") if isinstance(candidate.get("data"), dict) else {}
        failures: list[str] = []
        changes: list[str] = []
        if not isinstance(candidate, dict):
            failures.append("schema_json_object_required")
            changes.append("Return a JSON object for this stage.")
        if self._has_unresolved_templates(candidate):
            failures.append("unresolved_template_reference")
            changes.append("Resolve workflow references from verified previous stage outputs before passing to the next layer.")
        if stage == "intent_recognition":
            # This layer may declare that external/live material is required, but
            # it must not execute retrieval or synthesize unavailable facts.
            has_signal = self._candidate_has_required_stage_signal(node_id=stage, candidate=candidate)
            if not has_signal:
                failures.append("intent_execution_signal_missing")
                changes.append("Return the recognized execution signal, source contract, source policy, and missing information without executing the task.")
            if self._candidate_contains_user_facing_material(candidate):
                failures.append("intent_contains_execution_material")
                changes.append("Remove user-facing execution material from the intent stage and keep only planning-safe intent data.")
        elif stage == "workflow_planning":
            if not (candidate.get("execution_plan") or candidate.get("plan") or data.get("execution_plan") or data.get("steps") or data.get("graph")):
                failures.append("workflow_plan_missing")
                changes.append("Return a locked execution plan or graph derived from verified prior stage results.")
        elif stage == "agent_action_planning":
            if not (candidate.get("actions") or data.get("actions") or candidate.get("execution_method") or data.get("execution_method") or candidate.get("_executor_type")):
                failures.append("action_plan_missing")
                changes.append("Return executable action planning data based on the locked workflow plan.")
        elif stage == "result_verification":
            if not (candidate.get("verified") is True or candidate.get("status") in {"verified", "passed", "success"} or data.get("verified") is True):
                if not (candidate.get("message") or candidate.get("failure_class") or data):
                    failures.append("verification_result_missing")
                    changes.append("Return verification status with evidence, findings, or failure details.")
        elif stage == "final_synthesis":
            if not (candidate.get("final_answer") or candidate.get("message") or data.get("final_answer") or data.get("content")):
                failures.append("final_output_missing")
                changes.append("Return final user-facing output from verified stage results only.")
        passed = not failures
        return self._normalize_judgment({
            "passed": passed,
            "confidence": 0.96 if passed else 0.82,
            "quality": 0.96 if passed else 0.65,
            "consensus": 0.95 if passed else 0.7,
            "reason": "Stage output satisfies deterministic layer contract." if passed else "Stage output failed deterministic layer contract validation.",
            "failed_contracts": failures,
            "required_changes": changes,
            "correction_prompt": "\n".join(changes),
            "attempt_index": attempt_index,
            "verified_stage_id": node_id,
            "stage_contract_guard": {"status": "local_contract", "passed": passed},
        })

    def _candidate_has_required_stage_signal(self, *, node_id: str, candidate: dict[str, Any]) -> bool:
        stage = str(node_id or "")
        data = candidate.get("data") if isinstance(candidate.get("data"), dict) else {}
        if stage == "intent_recognition":
            return bool(
                candidate.get("intent_record")
                or data.get("execution_method")
                or data.get("source_contract")
                or data.get("source_policy")
                or "missing_information" in data
                or "missing_information" in candidate
            )
        return True

    def _criticism_crosses_layer_boundary(self, *, node_id: str, text: str) -> bool:
        stage = str(node_id or "")
        lowered = (text or "").lower()
        execution_demands = [
            "execute the", "perform the", "run the", "retrieve ", "fetch ", "collect ",
            "return the results", "return results", "generate the required content",
            "produce the final", "send ", "call the", "use the tool",
        ]
        non_execution_stages = {"input_parsing", "intent_recognition", "requirement_completion", "context_awareness", "workflow_planning", "agent_action_planning"}
        if stage in non_execution_stages and any(token in lowered for token in execution_demands):
            return True
        if stage == "intent_recognition" and ("remove all planning metadata" in lowered or "remove execution parameters" in lowered):
            # The intent layer is allowed to output planning-safe execution signals.
            return True
        return False

    def _meta_references_absent_context(self, *, candidate: dict[str, Any], text: str) -> bool:
        if not text:
            return False
        lowered = text.lower()
        candidate_text = json.dumps(candidate, ensure_ascii=False, default=str).lower()
        # Generic section names that often appear when the meta verifier is
        # accidentally judging a previous or unrelated sample.
        suspicious_names = [
            "runtime section", "runtime system metadata", "current_datetime_utc", "current_date_utc",
            "timezone_hint", "locale_hint", "normalized_intent section", "normalized_intent",
        ]
        return any(name in lowered and name not in candidate_text for name in suspicious_names)

    def _candidate_contains_user_facing_material(self, candidate: dict[str, Any]) -> bool:
        text = json.dumps(candidate, ensure_ascii=False, default=str).lower()
        markers = ["final_answer", "final_output", "user_facing_output", "<html", "<body", "</p>", "</li>"]
        return any(marker in text for marker in markers)

    def _has_unresolved_templates(self, value: Any) -> bool:
        text = json.dumps(value, ensure_ascii=False, default=str)
        return "{{" in text and "}}" in text

    def _judgment_text(self, judgment: dict[str, Any]) -> str:
        parts: list[str] = []
        for key in ("reason", "correction_prompt"):
            if judgment.get(key):
                parts.append(str(judgment.get(key)))
        for key in ("failed_contracts", "required_changes"):
            value = judgment.get(key)
            if isinstance(value, list):
                parts.extend(str(item) for item in value)
        return "\n".join(parts)

    async def _regenerate(self, *, node_id: str, state: dict[str, Any], current: dict[str, Any], correction_prompt: str, adapter: dict[str, Any], prompt: dict[str, Any], rendered_user_prompt: str, schema: dict[str, Any], router: Any, run_id: str, attempt_index: int) -> dict[str, Any]:
        repair_adapter = {
            **adapter,
            "adapter_id": str(adapter.get("adapter_id") or node_id) + "::verification_repair",
            "model_verification_repair_attempt": attempt_index,
            "disable_model_verification_loop": True,
        }
        repair_prompt = {
            **prompt,
            "system": str(prompt.get("system") or "") + (
                "\n\nVerification repair mode: regenerate the same stage output. "
                "Apply only accepted verification feedback. Keep the output schema unchanged. Return JSON only."
            ),
        }
        repair_payload = {
            "original_prompt": rendered_user_prompt,
            "previous_candidate_output": current,
            "accepted_verification_feedback": correction_prompt,
            "repair_rules": {
                "keep_schema": True,
                "do_not_change_stage_role": True,
                "do_not_invent_missing_facts": True,
                "use_only_available_context_and_verified_evidence": True,
                "repair_only_declared_defects": True,
            },
        }
        return await router.generate_json(
            run_id=run_id,
            node_id=f"{node_id}::verification_repair",
            adapter=repair_adapter,
            prompt=repair_prompt,
            rendered_user_prompt=json.dumps(repair_payload, ensure_ascii=False, default=str),
            schema=schema,
        )

    def _verification_adapter(self, adapter: dict[str, Any], *, suffix: str) -> dict[str, Any]:
        return {
            **(adapter or {}),
            "adapter_id": f"verification_brain_model_loop_{suffix}",
            "route_name": "verification_brain",
            "model_route_name": "verification_brain",
            "task_type": "model_stage_verification",
            "force_json": True,
            "disable_model_verification_loop": True,
        }

    def _normalize_judgment(self, judgment: dict[str, Any]) -> dict[str, Any]:
        data = dict(judgment or {})
        data["passed"] = bool(data.get("passed") is True)
        for key in ("confidence", "quality", "consensus"):
            data[key] = ConvergenceController._ratio(data.get(key), 1.0 if data.get("passed") else 0.0)
        if not isinstance(data.get("failed_contracts"), list):
            data["failed_contracts"] = [] if data.get("passed") else ["unspecified_contract_failure"]
        if not isinstance(data.get("required_changes"), list):
            data["required_changes"] = []
        data["reason"] = str(data.get("reason") or "")
        data["correction_prompt"] = str(data.get("correction_prompt") or "")
        data.setdefault("meta_verified", True)
        return data

    def _correction_prompt(self, judgment: dict[str, Any]) -> str:
        value = judgment.get("correction_prompt")
        if isinstance(value, str) and value.strip():
            return value.strip()[:2400]
        changes = judgment.get("required_changes")
        if isinstance(changes, list) and changes:
            return "\n".join(str(x) for x in changes if str(x).strip())[:2400]
        reason = judgment.get("reason")
        return str(reason or "").strip()[:1200]

    def _stage_responsibility(self, node_id: str) -> dict[str, Any]:
        generic = {
            "must_return_schema_compliant_json": True,
            "must_not_invent_unavailable_facts": True,
            "must_not_mix_task_metadata_with_execution_parameters": True,
            "must_preserve_layer_boundary": True,
        }
        table = {
            "input_parsing": {**generic, "purpose": "normalize incoming material into text, metadata, and explicit fields only"},
            "intent_recognition": {**generic, "purpose": "understand request shape and separate known execution parameters from semantic unknowns", "must_not_mark_unknown_external_facts_as_known": True},
            "requirement_completion": {**generic, "purpose": "identify missing required parameters without executing the task"},
            "context_awareness": {**generic, "purpose": "bind current input to runtime context without re-deciding execution"},
            "workflow_planning": {**generic, "purpose": "lock a safe execution graph and execution methods from verified intent and completed requirements", "must_not_select_generation_when_external_material_is_required_but_absent": True},
            "agent_action_planning": {**generic, "purpose": "select executable actions according to the locked workflow plan only", "must_not_override_locked_execution_method": True},
            "result_verification": {**generic, "purpose": "verify execution results against output contracts and evidence support", "must_not_pass_when_user_facing_output_is_missing": True},
            "final_synthesis": {**generic, "purpose": "produce user-facing output only from verified results and presentation material", "must_not_export_failure_or_unverified_material_as_success": True},
        }
        return table.get(str(node_id or ""), generic)

    def _compact_previous_results(self, results: Any) -> dict[str, Any]:
        if not isinstance(results, dict):
            return {}
        keys = ["input_parsing", "intent_recognition", "requirement_completion", "context_awareness", "workflow_planning", "agent_action_planning", "execution", "result_verification"]
        compact: dict[str, Any] = {}
        for key in keys:
            if key in results:
                compact[key] = self._clip(results.get(key), limit=2500)
        return compact

    def _clip(self, value: Any, *, limit: int) -> Any:
        text = json.dumps(value, ensure_ascii=False, default=str)
        if len(text) <= limit:
            return value
        return {"_summary": text[:limit], "_truncated": True}

    def _positive_int(self, value: Any, default: int) -> int:
        try:
            parsed = int(value)
            return parsed if parsed >= 0 else default
        except Exception:
            return default

    def _judgment_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "passed": {"type": "boolean"},
                "confidence": {"type": "number"},
                "quality": {"type": "number"},
                "consensus": {"type": "number"},
                "reason": {"type": "string"},
                "failed_contracts": {"type": "array", "items": {"type": "string"}},
                "required_changes": {"type": "array", "items": {"type": "string"}},
                "correction_prompt": {"type": "string"},
            },
            "required": ["passed", "reason", "correction_prompt"],
            "additionalProperties": True,
        }

    def _meta_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "accepted": {"type": "boolean"},
                "confidence": {"type": "number"},
                "reason": {"type": "string"},
                "replacement_correction_prompt": {"type": "string"},
            },
            "required": ["accepted", "reason"],
            "additionalProperties": True,
        }
