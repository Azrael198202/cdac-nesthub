from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StageContract:
    stage_id: str
    owner: str
    allowed_decisions: tuple[str, ...]
    forbidden_decisions: tuple[str, ...]
    output_key: str
    executor_type: str


PIPELINE_STAGES: tuple[StageContract, ...] = (
    StageContract(
        stage_id="input_parsing",
        owner="normalize incoming payloads into text and metadata",
        allowed_decisions=("extract_explicit_fields", "preserve_raw_input", "normalize_modality"),
        forbidden_decisions=("business_execution", "tool_selection", "provider_selection", "workflow_locking"),
        output_key="input_record",
        executor_type="llm_json",
    ),
    StageContract(
        stage_id="intent_recognition",
        owner="classify user intent and initial capability needs",
        allowed_decisions=("classify_intent", "estimate_capability_needs", "draft_non_executable_steps", "detect_missing_information"),
        forbidden_decisions=("execution_method_locking", "tool_selection", "provider_selection", "runtime_execution"),
        output_key="intent_record",
        executor_type="llm_json",
    ),
    StageContract(
        stage_id="requirement_completion",
        owner="verify required parameters against the recognized intent and either continue or request missing information through UI",
        allowed_decisions=("required_parameter_check", "pause_for_missing_information", "merge_user_supplied_parameters"),
        forbidden_decisions=("tool_selection", "provider_selection", "runtime_execution", "final_answer_creation"),
        output_key="requirement_record",
        executor_type="static_transform",
    ),
    StageContract(
        stage_id="context_awareness",
        owner="prepare minimal clean context for planning from upstream keys only",
        allowed_decisions=("session_state_read", "continuation_classification", "strict_context_reduction", "dependency_safe_summary"),
        forbidden_decisions=("business_intent_reclassification", "execution_method_locking", "tool_selection", "runtime_execution"),
        output_key="context_record",
        executor_type="static_transform",
    ),
    StageContract(
        stage_id="workflow_planning",
        owner="create executable workflow, graphs, dependencies, execution methods, source policy, and execution plan",
        allowed_decisions=("workflow_generation", "agent_graph_generation", "dependency_mapping", "execution_method_locking", "source_policy_locking"),
        forbidden_decisions=("runtime_execution", "result_synthesis", "unplanned_fallback"),
        output_key="execution_plan",
        executor_type="llm_json",
    ),
    StageContract(
        stage_id="execution_preparation",
        owner="prepare executable resources required by the locked workflow without executing the workflow",
        allowed_decisions=("resource_bundle_generation", "prompt_contract_generation", "tool_design_generation", "sandbox_precheck", "source_collection"),
        forbidden_decisions=("business_intent_reclassification", "runtime_execution", "unplanned_provider_selection", "final_answer_creation"),
        output_key="execution_preparation_record",
        executor_type="static_transform",
    ),
    StageContract(
        stage_id="pre_execution_validation",
        owner="validate schema, parameters, tools, confirmation gates, and sandbox executability before execution",
        allowed_decisions=("schema_check", "parameter_check", "tool_presence_check", "generation_need_check", "confirmation_need_check", "sandbox_executability_check"),
        forbidden_decisions=("intent_reclassification", "execution_policy_rewrite", "runtime_execution", "final_answer_creation"),
        output_key="validation_record",
        executor_type="static_transform",
    ),
    StageContract(
        stage_id="execution",
        owner="execute only the locked plan and prepared resources",
        allowed_decisions=("planned_tool_call", "planned_provider_call", "planned_runtime_call", "trace_recording", "evidence_recording"),
        forbidden_decisions=("intent_reclassification", "execution_method_reselection", "unplanned_search", "final_answer_creation"),
        output_key="execution_record",
        executor_type="tool_call",
    ),
    StageContract(
        stage_id="result_verification",
        owner="verify execution evidence and step satisfaction",
        allowed_decisions=("real_execution_check", "step_satisfaction_check", "confidence_check", "planned_fallback_gate"),
        forbidden_decisions=("new_fact_creation", "unplanned_search", "execution_policy_rewrite", "final_answer_creation"),
        output_key="verification_record",
        executor_type="static_transform",
    ),
    StageContract(
        stage_id="feedback_repair",
        owner="route repair using only allowed recovery paths",
        allowed_decisions=("json_repair", "missing_parameter_redirect", "planned_fallback_retry", "failure_reason_output"),
        forbidden_decisions=("business_logic_injection", "unplanned_tool_selection", "unplanned_provider_selection", "new_fact_creation"),
        output_key="repair_record",
        executor_type="static_transform",
    ),
    StageContract(
        stage_id="final_synthesis",
        owner="compose final answer from verified results only",
        allowed_decisions=("collect_step_outputs", "organize_by_original_question", "provenance_preserving_summary"),
        forbidden_decisions=("runtime_execution", "new_search", "new_fact_creation", "tool_selection"),
        output_key="final_record",
        executor_type="output",
    ),
)


class PipelineStageContract:
    def __init__(self, stages: tuple[StageContract, ...] = PIPELINE_STAGES) -> None:
        self.stages = stages
        self.by_id = {stage.stage_id: stage for stage in stages}

    def ordered_stage_ids(self) -> list[str]:
        return [stage.stage_id for stage in self.stages]

    def default_workflow_nodes(self) -> list[dict[str, str]]:
        return [
            {"id": stage.stage_id, "node_config": f"runtime/generated/nodes/{stage.stage_id}.yaml"}
            for stage in self.stages
        ]

    def node_config(self, stage_id: str) -> dict[str, Any]:
        stage = self.by_id[stage_id]
        cfg: dict[str, Any] = {
            "node_id": stage.stage_id,
            "executor_type": stage.executor_type,
            "prompt": f"runtime/generated/prompts/{stage.stage_id}.yaml",
            "output_schema": f"runtime/generated/schemas/{stage.stage_id}.schema.json",
            "capabilities": ["generic_runtime_stage"],
            "stage_contract": {
                "owner": stage.owner,
                "allowed_decisions": list(stage.allowed_decisions),
                "forbidden_decisions": list(stage.forbidden_decisions),
                "output_key": stage.output_key,
            },
            "review_required": stage.executor_type == "llm_json",
            "progress_weight": 10,
        }
        if stage.executor_type == "llm_json":
            cfg["adapter"] = f"runtime/generated/adapters/{stage.stage_id}.yaml"
        return cfg

    def generic_schema(self, stage_id: str) -> dict[str, Any]:
        stage = self.by_id[stage_id]
        return {
            "type": "object",
            "properties": {
                "_executor_type": {"type": "string"},
                "_node_id": {"type": "string"},
                "_status": {"type": "string"},
                stage.output_key: {"type": "object", "additionalProperties": True},
                "status": {"type": "string"},
                "message": {"type": "string"},
                "data": {"type": "object", "additionalProperties": True},
            },
            "additionalProperties": True,
        }

    def prompt_template(self, stage_id: str) -> dict[str, Any]:
        stage = self.by_id[stage_id]
        return {
            "id": f"{stage.stage_id}_prompt",
            "version": "4.4-ranked-execution-decision",
            "executor_type": stage.executor_type,
            "system": (
                "Return one JSON object only. Follow the stage boundary exactly. "
                "Use domain-neutral fields. Do not introduce concrete business rules, providers, tools, APIs, files, or facts unless supplied by upstream state. "
                "Every stage must carry forward the minimal upstream keys needed by the next stage."
            ),
            "user_template": "INPUT={{ user_input }}\nSTATE={{ previous_results }}\nRUNTIME={{ runtime_context }}",
            "runtime_rules": [
                f"Stage owner: {stage.owner}.",
                "Allowed decisions: " + ", ".join(stage.allowed_decisions),
                "Forbidden decisions: " + ", ".join(stage.forbidden_decisions),
                f"Write primary result under {stage.output_key} when applicable.",
                "For workflow planning, first read the upstream intent/objective and known parameters, then rank the fixed execution options: call_llm, generate_code, generate_shell, call_api, web_query, use_existing_tool, read_knowledge, ask_user, no_op.",
                "Workflow planning MUST output execution_decision with ranked_options and selected_action_type. Do not hide the decision inside a free-text action name.",
                "Each executable step must copy the selected action_type from execution_decision unless it has a separately ranked execution_decision.",
                "Map action_type to execution_method deterministically: call_llm=content_generation, generate_code=runtime_generated_tool, generate_shell=shell, call_api=api_call, web_query=web_search, use_existing_tool=existing_tool, read_knowledge=knowledge_base, ask_user=human_interaction, no_op=no_op.",
                "For web_query or call_api, workflow_planning must state whether external resources are required; execution_preparation must prepare concrete targets/endpoints before execution.",
                "Execution may only run actions/resources approved by execution_preparation.",
                "Do not output placeholder key lists as the stage result.",
            ],
            "output_contract": {stage.output_key: "object"},
        }
