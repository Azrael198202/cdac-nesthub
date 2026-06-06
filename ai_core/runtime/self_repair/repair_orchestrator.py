from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ai_core.config.paths import RUNTIME_GENERATED, RUNTIME_TRACES
from ai_core.runtime.self_repair.engine import RuntimeSelfRepairEngine
from ai_core.runtime.self_repair.execution_failure_repair import ExecutionFailureRepairClassifier
from ai_core.runtime.self_repair.trace_logger import FeedbackRepairTraceLogger


class FeedbackRepairOrchestrator:
    """User-confirmed repair coordinator.

    ai_core diagnoses and proposes a repair. It does not silently patch runtime
    tools. Implementation patch requests are written for auxiliary_brain, which
    owns runtime capability implementation and verification.
    """

    def __init__(self, *, storage_root: Path | None = None) -> None:
        self.storage_root = storage_root or (RUNTIME_GENERATED / "feedback_repair")
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.logger = FeedbackRepairTraceLogger()
        self.classifier = ExecutionFailureRepairClassifier()
        self.engine = RuntimeSelfRepairEngine(storage_root=RUNTIME_GENERATED / "self_repair")

    def propose_for_tool_result(
        self,
        *,
        run_id: str,
        tool_id: str,
        profile_id: str,
        result: dict[str, Any],
        tool_spec: dict[str, Any],
        input_payload: dict[str, Any],
        expected_contract: dict[str, Any] | None = None,
        runtime_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run_id = run_id or f"repair_{uuid4().hex[:12]}"
        expected_contract = expected_contract if isinstance(expected_contract, dict) else {}
        runtime_state = runtime_state if isinstance(runtime_state, dict) else {}
        self.logger.record(run_id=run_id, stage="failure_received", status="started", payload={
            "tool_id": tool_id,
            "profile_id": profile_id,
            "result": self._redact(result),
            "input_payload": self._redact(input_payload),
        })
        diagnosis = self.classifier.classify(result=result, tool_spec=tool_spec)
        self.logger.record(run_id=run_id, stage="failure_classified", status=diagnosis.category, payload=diagnosis.to_dict())

        deterministic_plan: dict[str, Any] | None = None
        if diagnosis.category in {"parameter_problem"}:
            report = {
                "run_id": run_id,
                "stage": "runtime_tool_execution",
                "status": "failed",
                "message": diagnosis.technical_reason,
                "error_type": diagnosis.category,
                "payload": input_payload,
                "expected_contract": expected_contract,
                "runtime_state": runtime_state,
            }
            deterministic_plan = self.engine.plan(report).to_dict()
            self.logger.record(run_id=run_id, stage="deterministic_repair_planned", status=str(deterministic_plan.get("status")), payload=deterministic_plan)

        interaction = self._repair_interaction_contract(diagnosis=diagnosis, deterministic_plan=deterministic_plan)
        proposal = {
            "repair_id": self._new_repair_id(tool_id),
            "run_id": run_id,
            "tool_id": tool_id,
            "profile_id": profile_id,
            "status": interaction["status"] if diagnosis.repairable else "repair_not_available",
            "requires_user_confirmation": bool(interaction.get("requires_user_confirmation")),
            "requires_user_action": bool(interaction.get("requires_user_action")),
            "repair_route": interaction.get("repair_route"),
            "repair_owner": interaction.get("repair_owner"),
            "interaction_kind": interaction.get("interaction_kind"),
            "diagnosis": diagnosis.to_dict(),
            "user_message": self._user_message(diagnosis),
            "deterministic_plan": deterministic_plan,
            "capability_repair_available": diagnosis.category == "tool_implementation_problem",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        path = self._proposal_path(proposal["repair_id"])
        path.write_text(json.dumps({
            "proposal": proposal,
            "tool_spec": self._redact(tool_spec),
            "input_payload": self._redact(input_payload),
            "result": self._redact(result),
            "expected_contract": self._redact(expected_contract),
            "runtime_state": self._redact(runtime_state),
        }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        proposal["proposal_path"] = str(path)
        self.logger.record(run_id=run_id, stage="repair_proposal_created", status=proposal["status"], payload=proposal)
        self.logger.write_snapshot(run_id=run_id, name=f"proposal_{proposal['repair_id']}", payload=proposal)
        return proposal

    def apply(self, *, repair_id: str, approved: bool, modified_input: dict[str, Any] | None = None) -> dict[str, Any]:
        record = self._load_repair_record(repair_id)
        proposal = record.get("proposal") if isinstance(record.get("proposal"), dict) else {}
        run_id = str(proposal.get("run_id") or repair_id)
        if not approved:
            result = {"ok": False, "status": "repair_declined", "repair_id": repair_id, "message": "Repair was not approved by the user."}
            self.logger.record(run_id=run_id, stage="repair_confirmation", status="declined", payload=result)
            return result
        diagnosis = proposal.get("diagnosis") if isinstance(proposal.get("diagnosis"), dict) else {}
        category = str(diagnosis.get("category") or "")
        if category == "parameter_problem":
            result = self._apply_parameter_repair(record=record, modified_input=modified_input)
        elif category == "tool_implementation_problem":
            result = self._create_capability_patch_request(record=record)
        else:
            result = {
                "ok": False,
                "status": "manual_repair_required",
                "repair_id": repair_id,
                "message": "This failure category requires the user to update configuration, secret values, permissions, or external service state before retrying.",
                "diagnosis": diagnosis,
            }
        self.logger.record(run_id=run_id, stage="repair_apply", status=str(result.get("status")), payload=result)
        return result

    def _apply_parameter_repair(self, *, record: dict[str, Any], modified_input: dict[str, Any] | None) -> dict[str, Any]:
        proposal = record.get("proposal") if isinstance(record.get("proposal"), dict) else {}
        repair_id = str(proposal.get("repair_id") or "")
        original_input = record.get("input_payload") if isinstance(record.get("input_payload"), dict) else {}
        expected = record.get("expected_contract") if isinstance(record.get("expected_contract"), dict) else {}
        runtime_state = record.get("runtime_state") if isinstance(record.get("runtime_state"), dict) else {}
        if isinstance(modified_input, dict) and modified_input:
            repaired = dict(original_input)
            repaired.update(modified_input)
            validation = self.engine._validate(repaired_payload=repaired, expected=expected)  # intentionally generic existing validator
            return {"ok": bool(validation.get("passed")), "status": "repair_applied" if validation.get("passed") else "repair_validation_failed", "repair_id": repair_id, "repaired_input": repaired, "validation": validation}
        report = {
            "run_id": str(proposal.get("run_id") or ""),
            "stage": "runtime_tool_execution",
            "status": "failed",
            "message": str((proposal.get("diagnosis") or {}).get("technical_reason") or ""),
            "error_type": "parameter_problem",
            "payload": original_input,
            "expected_contract": expected,
            "runtime_state": runtime_state,
        }
        result = self.engine.repair(report, auto_apply=True).to_dict()
        result.update({"ok": bool(result.get("applied") and (result.get("validation") or {}).get("passed")), "repair_id": repair_id})
        return result

    def _create_capability_patch_request(self, *, record: dict[str, Any]) -> dict[str, Any]:
        proposal = record.get("proposal") if isinstance(record.get("proposal"), dict) else {}
        repair_id = str(proposal.get("repair_id") or self._new_repair_id("tool"))
        out_dir = RUNTIME_GENERATED / "capability_patch_requests"
        out_dir.mkdir(parents=True, exist_ok=True)
        request = {
            "request_id": repair_id,
            "status": "pending_auxiliary_brain_patch",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "tool_id": proposal.get("tool_id"),
            "profile_id": proposal.get("profile_id"),
            "diagnosis": proposal.get("diagnosis"),
            "repair_contract": {
                "owner": "auxiliary_brain",
                "required_steps": [
                    "read_failure_trace",
                    "generate_patch_outside_ai_core",
                    "run_sandbox_validation",
                    "run_execution_verification",
                    "register_new_version_only_if_verified",
                ],
            },
            "trace_hints": {
                "feedback_repair_trace": str(RUNTIME_TRACES / "feedback_repair" / f"{self._safe_name(str(proposal.get('run_id') or repair_id))}.jsonl"),
                "execution_traces_root": str(RUNTIME_TRACES / "executions"),
            },
        }
        path = out_dir / f"{repair_id}.json"
        path.write_text(json.dumps(request, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return {"ok": True, "status": "capability_patch_request_created", "repair_id": repair_id, "request_path": str(path), "request": request}


    def _repair_interaction_contract(self, *, diagnosis: Any, deterministic_plan: dict[str, Any] | None) -> dict[str, Any]:
        """Return the generic repair route for a diagnosed failure.

        The route is intentionally domain-neutral. It separates: user-owned
        material repair, user-owned runtime profile repair, and system-owned
        generated implementation repair.
        """
        category = str(getattr(diagnosis, "category", "") or "")
        plan = deterministic_plan if isinstance(deterministic_plan, dict) else {}
        can_auto_apply = bool(plan.get("can_auto_apply"))
        if category == "parameter_problem":
            if can_auto_apply:
                return {
                    "status": "system_parameter_repair_available",
                    "repair_route": "system_generated_binding_repair",
                    "repair_owner": "system",
                    "interaction_kind": "system_repair_confirmation",
                    "requires_user_confirmation": True,
                    "requires_user_action": False,
                }
            return {
                "status": "user_input_update_required",
                "repair_route": "user_input_repair",
                "repair_owner": "user",
                "interaction_kind": "input_update_required",
                "requires_user_confirmation": False,
                "requires_user_action": True,
            }
        if category == "configuration_problem":
            return {
                "status": "profile_configuration_update_required",
                "repair_route": "profile_configuration_repair",
                "repair_owner": "user",
                "interaction_kind": "profile_configuration_update_required",
                "requires_user_confirmation": False,
                "requires_user_action": True,
            }
        if category == "secret_problem":
            return {
                "status": "profile_secret_update_required",
                "repair_route": "profile_secret_repair",
                "repair_owner": "user",
                "interaction_kind": "profile_secret_update_required",
                "requires_user_confirmation": False,
                "requires_user_action": True,
            }
        if category == "tool_implementation_problem":
            return {
                "status": "system_capability_patch_confirmation_required",
                "repair_route": "system_generated_capability_patch",
                "repair_owner": "auxiliary_brain",
                "interaction_kind": "capability_patch_confirmation",
                "requires_user_confirmation": True,
                "requires_user_action": False,
            }
        return {
            "status": "manual_review_required" if getattr(diagnosis, "repairable", False) else "repair_not_available",
            "repair_route": "manual_review",
            "repair_owner": "user",
            "interaction_kind": "manual_review_required",
            "requires_user_confirmation": False,
            "requires_user_action": bool(getattr(diagnosis, "repairable", False)),
        }

    def _user_message(self, diagnosis: Any) -> str:
        return f"{diagnosis.user_title}\n{diagnosis.user_message}\nSuggested action: {diagnosis.suggested_action}"

    def _new_repair_id(self, value: str) -> str:
        safe = self._safe_name(value or "repair")
        return f"repair_{safe}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}"

    def _proposal_path(self, repair_id: str) -> Path:
        self.storage_root.mkdir(parents=True, exist_ok=True)
        return self.storage_root / f"{self._safe_name(repair_id)}.json"

    def _load_repair_record(self, repair_id: str) -> dict[str, Any]:
        path = self._proposal_path(repair_id)
        if not path.exists():
            return {"proposal": {"repair_id": repair_id, "status": "not_found"}}
        try:
            data = json.loads(path.read_text(encoding="utf-8") or "{}")
            return data if isinstance(data, dict) else {"proposal": {"repair_id": repair_id, "status": "invalid_record"}}
        except Exception as exc:
            return {"proposal": {"repair_id": repair_id, "status": "invalid_record", "error": str(exc)}}

    def _redact(self, value: Any) -> Any:
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for k, v in value.items():
                key = str(k).casefold()
                if any(token in key for token in ["secret", "credential", "password", "token"]):
                    out[k] = "***"
                else:
                    out[k] = self._redact(v)
            return out
        if isinstance(value, list):
            return [self._redact(x) for x in value]
        return value

    def _safe_name(self, value: str) -> str:
        return "".join(c if c.isalnum() or c in {"_", "-"} else "_" for c in str(value)).strip("_") or "unknown"
