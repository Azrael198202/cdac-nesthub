from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import FailureReport, RepairAction, RepairPlan, RepairResult
from .failure_classifier import FailureClassifier
from .parameter_repair import ParameterBindingRepairer
from .schema_repair import SchemaRepairer
from .state_repair import StateRepairer
from .variable_repair import VariableBindingRepairer


class RuntimeSelfRepairEngine:
    """Generic self-repair orchestrator for ai_core runtime failures.

    The engine is an additive component. It never changes business behavior by
    itself; callers explicitly pass a failure report and apply the returned
    repaired payload only after validation.
    """

    def __init__(self, *, storage_root: str | Path | None = None) -> None:
        self.storage_root = Path(storage_root) if storage_root else None
        self.classifier = FailureClassifier()
        self.schema_repairer = SchemaRepairer()
        self.parameter_repairer = ParameterBindingRepairer()
        self.variable_repairer = VariableBindingRepairer()
        self.state_repairer = StateRepairer()

    def diagnose(self, report: FailureReport | dict[str, Any]) -> dict[str, Any]:
        failure = self._normalize_report(report)
        classification = self.classifier.classify(failure)
        return {"failure": failure.to_dict(), "classification": classification}

    def plan(self, report: FailureReport | dict[str, Any]) -> RepairPlan:
        failure = self._normalize_report(report)
        diagnosis = self.classifier.classify(failure)
        category = diagnosis.get("category") or "unknown_failure"
        payload = self._payload(failure)
        expected = failure.expected_contract if isinstance(failure.expected_contract, dict) else {}
        state = failure.runtime_state if isinstance(failure.runtime_state, dict) else {}
        actions: list[RepairAction] = []

        if category == "schema_mismatch":
            schema = self._schema(expected)
            actions.extend(self.schema_repairer.plan(payload=payload, schema=schema))
        elif category == "unresolved_variable_binding":
            actions.extend(self.variable_repairer.plan(payload=payload, runtime_state=state))
        elif category == "missing_or_misbound_parameter":
            required = self._required(expected)
            aliases = expected.get("parameter_aliases") if isinstance(expected.get("parameter_aliases"), dict) else {}
            actions.extend(self.parameter_repairer.plan(provided=payload, required=required, aliases=aliases))
        elif category == "state_or_checkpoint_inconsistency":
            actions.extend(self.state_repairer.plan(runtime_state=state, storage_root=self.storage_root))

        if actions:
            return RepairPlan(
                status="repair_plan_ready",
                classification=str(category),
                actions=actions,
                requires_web_evidence=False,
                requires_human_review=not all(a.safe_to_apply for a in actions),
                reason="Deterministic repair actions were found.",
            )

        requires_web = bool(diagnosis.get("requires_web_evidence"))
        return RepairPlan(
            status="repair_plan_requires_external_knowledge" if requires_web else "repair_plan_not_available",
            classification=str(category),
            actions=[],
            requires_web_evidence=requires_web,
            requires_human_review=True,
            reason="No safe deterministic repair was found.",
        )

    def repair(self, report: FailureReport | dict[str, Any], *, auto_apply: bool = True) -> RepairResult:
        failure = self._normalize_report(report)
        plan = self.plan(failure)
        payload = self._payload(failure)
        if not auto_apply or not plan.can_auto_apply:
            return RepairResult(
                status="repair_planned_not_applied",
                applied=False,
                repaired_payload=payload,
                plan=plan.to_dict(),
                validation={"passed": False, "status": "not_applied"},
                reason=plan.reason,
            )
        repaired = self._apply(payload=payload, runtime_state=failure.runtime_state, actions=plan.actions)
        validation = self._validate(repaired_payload=repaired, expected=failure.expected_contract)
        return RepairResult(
            status="repair_applied" if validation.get("passed") else "repair_applied_validation_failed",
            applied=True,
            repaired_payload=repaired,
            plan=plan.to_dict(),
            validation=validation,
            reason="Repair applied and validated." if validation.get("passed") else "Repair applied but validation did not pass.",
        )

    def write_trace(self, *, result: RepairResult | RepairPlan | dict[str, Any], trace_dir: str | Path, name: str) -> Path:
        out_dir = Path(trace_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{name}.json"
        if hasattr(result, "to_dict"):
            data = result.to_dict()  # type: ignore[assignment]
        else:
            data = result
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return path

    def _normalize_report(self, report: FailureReport | dict[str, Any]) -> FailureReport:
        if isinstance(report, FailureReport):
            return report
        data = dict(report or {})
        return FailureReport(
            run_id=str(data.get("run_id") or ""),
            node_id=str(data.get("node_id") or ""),
            stage=str(data.get("stage") or ""),
            status=str(data.get("status") or "failed"),
            message=str(data.get("message") or ""),
            error_type=str(data.get("error_type") or ""),
            payload=data.get("payload") if isinstance(data.get("payload"), dict) else {},
            expected_contract=data.get("expected_contract") if isinstance(data.get("expected_contract"), dict) else {},
            actual_material=data.get("actual_material") if isinstance(data.get("actual_material"), dict) else {},
            runtime_state=data.get("runtime_state") if isinstance(data.get("runtime_state"), dict) else {},
        )

    def _payload(self, failure: FailureReport) -> dict[str, Any]:
        payload = failure.payload if isinstance(failure.payload, dict) else {}
        if isinstance(payload.get("input"), dict):
            return dict(payload["input"])
        if isinstance(payload.get("parameters"), dict):
            return dict(payload["parameters"])
        return dict(payload)

    def _schema(self, expected: dict[str, Any]) -> dict[str, Any]:
        for key in ["json_schema", "input_schema", "schema"]:
            if isinstance(expected.get(key), dict):
                return expected[key]
        return expected if isinstance(expected.get("properties"), dict) else {}

    def _required(self, expected: dict[str, Any]) -> list[str]:
        for key in ["required", "required_parameters"]:
            value = expected.get(key)
            if isinstance(value, list):
                return [str(x) for x in value]
        schema = self._schema(expected)
        value = schema.get("required") if isinstance(schema, dict) else None
        return [str(x) for x in value] if isinstance(value, list) else []

    def _apply(self, *, payload: dict[str, Any], runtime_state: dict[str, Any], actions: list[RepairAction]) -> dict[str, Any]:
        out = dict(payload)
        schema_actions = [a for a in actions if a.action_type == "schema_type_coercion"]
        parameter_actions = [a for a in actions if a.action_type == "parameter_alias_binding"]
        variable_actions = [a for a in actions if a.action_type == "variable_binding_resolution"]
        if parameter_actions:
            out = self.parameter_repairer.apply(provided=out, actions=parameter_actions)
        if variable_actions:
            out = self.variable_repairer.apply(payload=out, actions=variable_actions)
        if schema_actions:
            out = self.schema_repairer.apply(payload=out, actions=schema_actions)
        return out

    def _validate(self, *, repaired_payload: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
        schema = self._schema(expected)
        if schema:
            return self.schema_repairer.validate_minimal(payload=repaired_payload, schema=schema)
        required = self._required(expected)
        missing = [k for k in required if k not in repaired_payload or repaired_payload.get(k) in (None, "")]
        return {"passed": not missing, "missing": missing}
