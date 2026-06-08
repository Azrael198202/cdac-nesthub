from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class LayerContract:
    """Runtime layer boundary contract.

    The contract is intentionally domain-neutral.  It describes what a layer may
    read, what it must emit, and which brain/model route should be used.  It is
    used by validation and bootstrap code to prevent accidental layer overlap,
    business-specific shortcuts, or execution-time re-planning.
    """

    layer_id: str
    owner_brain: str
    input_keys: tuple[str, ...]
    output_keys: tuple[str, ...]
    allowed_decisions: tuple[str, ...]
    forbidden_decisions: tuple[str, ...]
    model_task_type: str = "none"
    model_complexity: str = "default"
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("input_keys", "output_keys", "allowed_decisions", "forbidden_decisions", "notes"):
            data[key] = list(data[key])
        return data


class RuntimeLayerContractRegistry:
    """Single source of truth for AI Runtime OS layer boundaries."""

    def __init__(self, contracts: list[LayerContract] | None = None) -> None:
        self._contracts = contracts or default_layer_contracts()

    def ordered(self) -> list[LayerContract]:
        return list(self._contracts)

    def by_id(self, layer_id: str) -> LayerContract | None:
        for item in self._contracts:
            if item.layer_id == layer_id:
                return item
        return None

    def as_manifest(self) -> dict[str, Any]:
        return {
            "schema_version": "runtime_layer_contract.v1",
            "boundary_rule": "ai_core remains a generic runtime OS; runtime capabilities are generated, registered, executed, and verified outside fixed business code.",
            "contracts": [item.to_dict() for item in self._contracts],
        }

    def validate(self) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, item in enumerate(self._contracts, start=1):
            if item.layer_id in seen:
                findings.append({"level": "error", "layer_id": item.layer_id, "message": "duplicate_layer_id"})
            seen.add(item.layer_id)
            overlap = sorted(set(item.allowed_decisions).intersection(item.forbidden_decisions))
            if overlap:
                findings.append({"level": "error", "layer_id": item.layer_id, "message": "decision_boundary_overlap", "overlap": overlap})
            if not item.input_keys or not item.output_keys:
                findings.append({"level": "error", "layer_id": item.layer_id, "message": "missing_io_contract"})
            if index >= 7 and "replan" in item.allowed_decisions:
                findings.append({"level": "error", "layer_id": item.layer_id, "message": "late_layer_may_not_replan"})
        return {"ok": not any(x.get("level") == "error" for x in findings), "findings": findings, "count": len(self._contracts)}


def default_layer_contracts() -> list[LayerContract]:
    return [
        LayerContract(
            layer_id="perception",
            owner_brain="perception_brain",
            input_keys=("raw_text", "uploaded_artifacts", "transport_metadata"),
            output_keys=("normalized_text", "artifact_observations", "perception_metadata"),
            allowed_decisions=("modality_detection", "content_extraction", "artifact_summary"),
            forbidden_decisions=("intent_classification", "workflow_planning", "execution_method_selection", "tool_execution"),
            model_task_type="perception_summary",
            model_complexity="basic",
        ),
        LayerContract(
            layer_id="input_parsing",
            owner_brain="ai_core",
            input_keys=("normalized_text", "artifact_observations", "perception_metadata"),
            output_keys=("parsed_input", "explicit_fields", "raw_input_reference"),
            allowed_decisions=("structural_extraction", "language_hint", "metadata_normalization"),
            forbidden_decisions=("business_execution_decision", "tool_selection", "source_selection"),
            model_task_type="input_parsing",
            model_complexity="basic",
        ),
        LayerContract(
            layer_id="intent_recognition",
            owner_brain="ai_core",
            input_keys=("parsed_input", "clean_session_summary"),
            output_keys=("intent_contract", "capability_need_hints", "draft_steps", "missing_information_hints"),
            allowed_decisions=("intent_family", "task_type", "capability_need_hint", "missing_information_hint"),
            forbidden_decisions=("execution_method_lock", "provider_lock", "tool_execution"),
            model_task_type="intent_recognition",
            model_complexity="medium",
        ),
        LayerContract(
            layer_id="requirement_completion",
            owner_brain="auxiliary_brain",
            input_keys=("intent_contract", "known_parameters", "parameter_contracts"),
            output_keys=("completed_requirements", "pending_interaction_request", "known_parameters"),
            allowed_decisions=("required_parameter_check", "pause_for_missing_information", "resume_after_user_input"),
            forbidden_decisions=("workflow_replanning", "source_selection", "tool_execution"),
            model_task_type="requirement_completion",
            model_complexity="basic",
        ),
        LayerContract(
            layer_id="context_awareness",
            owner_brain="memory_brain",
            input_keys=("session_state", "pending_interaction_request", "latest_user_input", "completed_requirements"),
            output_keys=("clean_context", "context_binding_decision", "safe_shared_summaries"),
            allowed_decisions=("parameter_binding", "resume_or_new_task_classification", "context_scope_filtering"),
            forbidden_decisions=("business_intent_reclassification", "execution_method_selection", "tool_execution"),
            model_task_type="context_awareness",
            model_complexity="basic",
        ),
        LayerContract(
            layer_id="workflow_planning",
            owner_brain="ai_core",
            input_keys=("intent_contract", "completed_requirements", "clean_context", "runtime_capability_registry"),
            output_keys=("execution_plan", "task_graph", "agent_graph", "locked_execution_methods"),
            allowed_decisions=("graph_generation", "dependency_detection", "execution_method_lock", "source_policy_lock", "fallback_policy_lock"),
            forbidden_decisions=("tool_execution", "result_synthesis", "unplanned_fallback"),
            model_task_type="workflow_planning",
            model_complexity="high",
        ),
        LayerContract(
            layer_id="pre_execution_validation",
            owner_brain="verification_brain",
            input_keys=("execution_plan", "known_parameters", "runtime_capability_registry", "approval_policy"),
            output_keys=("validation_report", "blocked_steps", "approval_requests"),
            allowed_decisions=("schema_check", "parameter_completeness_check", "capability_existence_check", "approval_check"),
            forbidden_decisions=("intent_reclassification", "execution_method_rewrite", "tool_execution"),
            model_task_type="pre_execution_validation",
            model_complexity="medium",
        ),
        LayerContract(
            layer_id="execution",
            owner_brain="runtime_kernel",
            input_keys=("execution_plan", "validated_parameters", "approval_state"),
            output_keys=("step_results", "evidence", "provenance", "trace"),
            allowed_decisions=("execute_locked_step", "record_trace", "record_evidence"),
            forbidden_decisions=("intent_reclassification", "execution_method_rewrite", "unplanned_source_selection", "final_synthesis"),
            model_task_type="execution_support",
            model_complexity="default",
        ),
        LayerContract(
            layer_id="result_verification",
            owner_brain="verification_brain",
            input_keys=("step_results", "evidence", "provenance", "execution_plan"),
            output_keys=("verification_report", "accepted_material", "planned_fallback_request"),
            allowed_decisions=("real_execution_check", "step_satisfaction_check", "confidence_check", "planned_fallback_request"),
            forbidden_decisions=("intent_reclassification", "new_search", "new_tool_selection", "unplanned_fallback", "fact_invention"),
            model_task_type="result_verification",
            model_complexity="medium",
        ),
        LayerContract(
            layer_id="feedback_repair",
            owner_brain="repair_brain",
            input_keys=("verification_report", "failure_report", "execution_plan", "user_feedback"),
            output_keys=("repair_plan", "resume_boundary", "explicit_failure_reason"),
            allowed_decisions=("schema_repair", "parameter_repair_route", "planned_fallback_route", "stop_after_budget"),
            forbidden_decisions=("new_business_rule", "silent_execution_method_change", "unsupported_success_claim"),
            model_task_type="feedback_repair",
            model_complexity="medium",
        ),
        LayerContract(
            layer_id="final_synthesis",
            owner_brain="presentation_brain",
            input_keys=("accepted_material", "verification_report", "original_user_request", "presentation_profile"),
            output_keys=("final_answer", "artifacts", "public_trace_summary"),
            allowed_decisions=("answer_assembly", "format_selection", "failure_presentation"),
            forbidden_decisions=("re_execution", "new_search", "new_fact_creation", "tool_selection"),
            model_task_type="final_synthesis",
            model_complexity="basic",
        ),
    ]
