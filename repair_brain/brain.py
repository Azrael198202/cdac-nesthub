from __future__ import annotations

from typing import Any

from auxiliary_brain.runtime.self_repair.execution_failure_repair import ExecutionFailureRepairClassifier
from evidence_engine import EvidenceRequest, RuntimeEvidenceCollector
from memory_brain import MemoryRecord, RuntimeMemoryStore
from repair_brain.contracts import RepairPlan, RepairRequest
from verification_brain import RuntimeVerificationBrain, VerificationExpectation
from ai_core.model_orchestration import LiteLLMBrainClient


class RuntimeRepairBrain:
    """Separated repair-brain facade.

    This class does not replace existing behavior yet. It provides the stable
    interface for the next self-repair phase while delegating current generic
    classification to the already verified ai_core self-repair implementation.
    """

    def __init__(self) -> None:
        self.classifier = ExecutionFailureRepairClassifier()
        self.evidence = RuntimeEvidenceCollector()
        self.memory = RuntimeMemoryStore()
        self.verifier = RuntimeVerificationBrain()
        self.llm = LiteLLMBrainClient()

    def analyze(self, request: RepairRequest | dict[str, Any]) -> RepairPlan:
        req = request if isinstance(request, RepairRequest) else RepairRequest(
            run_id=str((request or {}).get("run_id") or ""),
            component=str((request or {}).get("component") or ""),
            failure=(request or {}).get("failure") if isinstance((request or {}).get("failure"), dict) else {},
            context=(request or {}).get("context") if isinstance((request or {}).get("context"), dict) else {},
            expected_contract=(request or {}).get("expected_contract") if isinstance((request or {}).get("expected_contract"), dict) else {},
        )
        evidence = self.evidence.collect(EvidenceRequest(
            run_id=req.run_id,
            task_name=str(req.context.get("task_name") or ""),
            participant_id=str(req.context.get("participant_id") or ""),
            event_name=str(req.context.get("event_name") or ""),
        ))
        diagnosis = self.classifier.classify(result=req.failure, tool_spec=req.context.get("tool_spec") if isinstance(req.context.get("tool_spec"), dict) else {})
        owner = "repair_brain"
        steps = ["collect_evidence", "classify_failure", "propose_repair"]
        if diagnosis.category == "tool_implementation_problem":
            owner = "auxiliary_brain"
            steps.extend(["generate_patch_outside_ai_core", "run_sandbox_validation", "run_execution_verification"])
        elif diagnosis.category == "parameter_problem":
            owner = "ai_core"
            steps.extend(["repair_structural_input", "validate_schema"])
        plan = RepairPlan(
            status="repair_plan_created" if diagnosis.repairable else "manual_review_required",
            category=diagnosis.category,
            owner=owner,
            steps=steps,
            requires_approval=diagnosis.requires_user_confirmation,
            evidence_summary=evidence.summary,
            payload={"diagnosis": diagnosis.to_dict(), "request": req.to_dict()},
        )
        self.memory.remember(MemoryRecord(
            memory_type="repair_analysis",
            category=diagnosis.category,
            component=req.component,
            summary=diagnosis.user_message,
            outcome=plan.status,
            confidence=diagnosis.confidence,
            evidence_refs=[item.source for item in evidence.items[:10]],
            payload={"repair_owner": owner, "steps": steps},
        ))
        return plan

    def verify_repair_output(self, *, output: Any, expectation: dict[str, Any] | None = None) -> dict[str, Any]:
        result = self.verifier.verify(output=output, expectation=VerificationExpectation(
            name=str((expectation or {}).get("name") or "repair_output_expectation"),
            rules=(expectation or {}).get("rules") if isinstance((expectation or {}).get("rules"), dict) else {},
        ))
        return result.to_dict()
