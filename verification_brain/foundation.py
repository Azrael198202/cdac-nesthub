from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_GENERATED, RUNTIME_TRACES
from evidence_engine import EvidenceRequest, RuntimeEvidenceCollector
from repair_brain import RepairRequest, RuntimeRepairBrain
from verification_brain import RuntimeVerificationBrain, VerificationExpectation


@dataclass
class RuntimeFailureReport:
    """Structured failure report produced by the verification foundation.

    The report is task/domain neutral.  It records structural facts: run id,
    task name, status, failed checks, evidence package path, and a suggested
    owner.  It is an observation artifact, not an automatic code patch.
    """

    report_id: str
    status: str
    task_name: str = ""
    run_id: str = ""
    graph_id: str = ""
    failure_class: str = "unknown_problem"
    failed_checks: list[dict[str, Any]] = field(default_factory=list)
    evidence_path: str = ""
    evidence_summary: dict[str, Any] = field(default_factory=dict)
    repair_plan: dict[str, Any] = field(default_factory=dict)
    suggested_owner: str = "human_review"
    suggested_location: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RuntimeVerificationFoundation:
    """Detect failure, collect evidence, classify, and explain where to repair.

    This is the v20 verification foundation layer.  It intentionally avoids editing code.
    It turns raw runtime execution output into a small, durable failure report
    using six generic verification levels: template, schema, dependency,
    capability, expectation, and side-effect.
    """

    FAILURE_STATUSES = {"failed", "error", "blocked", "requires_input", "requires_key", "paused", "not_found"}

    def __init__(self) -> None:
        self.verifier = RuntimeVerificationBrain()
        self.evidence = RuntimeEvidenceCollector()
        self.repair = RuntimeRepairBrain()
        self.report_root = RUNTIME_GENERATED / "failure_reports"
        self.report_root.mkdir(parents=True, exist_ok=True)

    def inspect_run(
        self,
        *,
        task_graph: dict[str, Any] | None,
        participants: list[dict[str, Any]] | None,
        run_payload: dict[str, Any] | None,
        stage: str = "post_execution",
    ) -> RuntimeFailureReport | None:
        task_graph = task_graph if isinstance(task_graph, dict) else {}
        run_payload = run_payload if isinstance(run_payload, dict) else {}
        participants = participants if isinstance(participants, list) else []
        task_name = str(run_payload.get("task_name") or task_graph.get("task_name") or task_graph.get("graph_id") or "").strip()
        run_id = str(run_payload.get("run_id") or "").strip()
        graph_id = str(run_payload.get("graph_id") or task_graph.get("graph_id") or task_name or "").strip()
        status = str(run_payload.get("status") or "completed").strip().lower()

        checks = self._structural_checks(task_graph=task_graph, participants=participants, run_payload=run_payload)
        verification_context = {
            "run_payload": run_payload,
            "task_graph": task_graph,
            "participants": participants,
        }
        verify_result = self.verifier.verify(
            output=verification_context,
            expectation=VerificationExpectation(
                name="runtime_post_execution_v20_six_level_expectation",
                rules={
                    "must_not_contain_unresolved_template": True,
                    "final_answer_required": True,
                },
            ),
        )
        checks.extend(verify_result.checks)
        failed_checks = [check for check in checks if check.get("passed") is False]
        if status not in self.FAILURE_STATUSES and not failed_checks:
            self._append_verification_event({
                "event": "verification_passed",
                "task_name": task_name,
                "run_id": run_id,
                "graph_id": graph_id,
                "status": status,
                "stage": stage,
            })
            return None

        failure_class = self._classify_failure(status=status, failed_checks=failed_checks, run_payload=run_payload)
        participant_id = self._first_failed_participant(failed_checks, run_payload)
        evidence_package = self.evidence.collect(EvidenceRequest(
            run_id=run_id,
            task_name=task_name,
            participant_id=participant_id,
            event_name=failure_class,
            max_lines_per_file=280,
        ))
        evidence_path = self.report_root / f"evidence_{run_id or self._safe_id(task_name) or 'unknown'}.json"
        self.evidence.write_package(evidence_package, output_path=evidence_path)

        repair_plan = self.repair.analyze(RepairRequest(
            run_id=run_id,
            component=participant_id or graph_id,
            failure={"status": status, "failure_class": failure_class, "failed_checks": failed_checks},
            context={"task_name": task_name, "participant_id": participant_id, "graph_id": graph_id, "event_name": failure_class},
            expected_contract={"generic_runtime_checks": True},
        ))
        suggested_owner, suggested_location = self._suggest_repair_location(failure_class, failed_checks, repair_plan.to_dict())
        report = RuntimeFailureReport(
            report_id=f"failure_{run_id or self._safe_id(task_name) or datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            status="failure_detected",
            task_name=task_name,
            run_id=run_id,
            graph_id=graph_id,
            failure_class=failure_class,
            failed_checks=failed_checks,
            evidence_path=str(evidence_path),
            evidence_summary=evidence_package.summary,
            repair_plan=repair_plan.to_dict(),
            suggested_owner=suggested_owner,
            suggested_location=suggested_location,
            payload={"runtime_status": status, "stage": stage},
        )
        self.write_report(report)
        return report

    def write_report(self, report: RuntimeFailureReport) -> Path:
        path = self.report_root / f"{report.report_id}.json"
        path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        self._append_verification_event({"event": "failure_detected", **report.to_dict()})
        return path

    def list_reports(self, *, limit: int = 50) -> list[dict[str, Any]]:
        reports: list[dict[str, Any]] = []
        for path in sorted(self.report_root.glob("failure_*.json"), key=lambda p: p.stat().st_mtime):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    data.setdefault("path", str(path))
                    reports.append(data)
            except Exception:
                continue
        return reports[-max(1, int(limit)):]

    def _structural_checks(self, *, task_graph: dict[str, Any], participants: list[dict[str, Any]], run_payload: dict[str, Any]) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []
        status = str(run_payload.get("status") or "").lower()
        checks.append({"name": "run_status_terminal_success", "passed": status in {"completed", "succeeded", "ok"}, "status": status})
        if status in {"requires_input", "paused", "requires_key"}:
            checks.append({"name": "run_must_not_wait_for_input_after_task_parameters", "passed": False, "status": status, "missing_inputs": run_payload.get("missing_inputs")})
        selected = [str(x).strip() for x in (task_graph.get("selected_participant_ids") or []) if str(x).strip()]
        if selected:
            results = run_payload.get("agent_results") if isinstance(run_payload.get("agent_results"), list) else []
            result_ids = {str(item.get("participant_id") or "").strip() for item in results if isinstance(item, dict)}
            missing = [pid for pid in selected if pid not in result_ids]
            if status in {"completed", "failed"} and missing:
                checks.append({"name": "selected_participants_have_results", "passed": False, "missing_participant_ids": missing})
        final_answer = ""
        synthesis = run_payload.get("synthesis") if isinstance(run_payload.get("synthesis"), dict) else {}
        final_answer = str(synthesis.get("final_answer") or run_payload.get("final_answer") or "")
        if "{{" in final_answer or "}}" in final_answer:
            checks.append({"name": "final_answer_must_not_contain_unresolved_template", "passed": False})
        for item in run_payload.get("agent_results") if isinstance(run_payload.get("agent_results"), list) else []:
            if not isinstance(item, dict):
                continue
            item_status = str(item.get("status") or "").lower()
            if item_status not in {"completed", "succeeded", "ok", "reused"}:
                checks.append({
                    "name": "participant_result_status_success",
                    "passed": False,
                    "participant_id": item.get("participant_id"),
                    "status": item_status,
                    "message": str(item.get("message") or item.get("error") or item.get("final_answer") or "")[:600],
                })
            workflow_results = item.get("workflow_results") if isinstance(item.get("workflow_results"), dict) else {}
            unresolved = workflow_results.get("unresolved_templates") if isinstance(workflow_results.get("unresolved_templates"), list) else []
            if unresolved:
                checks.append({
                    "name": "participant_input_must_not_contain_unresolved_template",
                    "passed": False,
                    "participant_id": item.get("participant_id"),
                    "unresolved_templates": unresolved[:20],
                })
            try:
                item_text = json.dumps({"workflow_results": workflow_results, "final_answer": item.get("final_answer")}, ensure_ascii=False, default=str)
            except Exception:
                item_text = str(item)
            if "{{" in item_text and "}}" in item_text:
                checks.append({
                    "name": "participant_result_must_not_contain_unresolved_template",
                    "passed": False,
                    "participant_id": item.get("participant_id"),
                })
        return checks

    def _classify_failure(self, *, status: str, failed_checks: list[dict[str, Any]], run_payload: dict[str, Any]) -> str:
        names = {str(check.get("name") or "") for check in failed_checks}
        levels = {int(check.get("level")) for check in failed_checks if str(check.get("level") or "").isdigit()}
        combined = json.dumps({"checks": failed_checks, "run": run_payload}, ensure_ascii=False, default=str).casefold()
        if 1 in levels or any("template" in name for name in names) or "{{" in combined or "}}" in combined:
            return "template_resolution_problem"
        if 2 in levels or "schema" in combined or "required_key" in names:
            return "schema_contract_problem"
        if 3 in levels or "selected_participants_have_results" in names or "dependency" in combined:
            return "dependency_mapping_problem"
        if 4 in levels or "capability" in combined or "tool" in combined:
            return "capability_execution_problem"
        if 5 in levels or "expectation" in combined or "placeholder" in combined:
            return "expectation_mismatch_problem"
        if 6 in levels or "side_effect" in combined:
            return "side_effect_verification_problem"
        if status in {"requires_input", "paused", "requires_key"} or "missing_inputs" in combined:
            return "parameter_binding_problem"
        if "not_found" in status or "not_found" in combined:
            return "runtime_artifact_lookup_problem"
        return "execution_verification_problem"

    def _first_failed_participant(self, failed_checks: list[dict[str, Any]], run_payload: dict[str, Any]) -> str:
        for check in failed_checks:
            value = str(check.get("participant_id") or "").strip()
            if value:
                return value
        pending = run_payload.get("pending_action") if isinstance(run_payload.get("pending_action"), dict) else {}
        return str(pending.get("participant_id") or pending.get("node_id") or "").strip()

    def _suggest_repair_location(self, failure_class: str, failed_checks: list[dict[str, Any]], repair_plan: dict[str, Any]) -> tuple[str, list[str]]:
        mapping = {
            "template_resolution_problem": ("ai_core", ["template resolution", "dependency mapping", "final_synthesis"]),
            "schema_contract_problem": ("verification_brain", ["schema contract", "result normalization", "parameter bridge"]),
            "dependency_mapping_problem": ("task_runtime", ["TaskGraph generation", "dependency mapping", "resume state"]),
            "parameter_binding_problem": ("auxiliary_brain", ["task parameter extraction", "preflight binding", "resume binding"]),
            "runtime_artifact_lookup_problem": ("task_runtime", ["task revision", "graph revision", "artifact lookup"]),
            "capability_execution_problem": ("auxiliary_brain", ["agent capability binding", "registered tool dispatch", "execution lock"]),
            "expectation_mismatch_problem": ("verification_brain", ["expectation generation", "result verification", "final synthesis contract"]),
            "side_effect_verification_problem": ("verification_brain", ["side-effect verification", "capability return schema", "external operation evidence"]),
            "graph_execution_mapping_problem": ("task_runtime", ["TaskGraph generation", "participant mapping"]),
        }
        return mapping.get(failure_class, (str(repair_plan.get("owner") or "repair_brain"), ["runtime traces", "failure evidence"]))

    def _append_verification_event(self, event: dict[str, Any]) -> None:
        try:
            path = RUNTIME_TRACES / "verification" / "verification_events.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"created_at": datetime.now(timezone.utc).isoformat(), **event}
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        except Exception:
            return

    def _safe_id(self, value: str) -> str:
        return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in str(value or "")).strip("_")[:80]
