from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import urllib.request
import urllib.error
import importlib.util
import importlib.machinery
import inspect
import ast
import io
import contextlib
import re
from pathlib import Path
from ai_core.runtime.generated_execution.source_safety import write_bounded_python_copy
from typing import Any
from datetime import datetime, timezone

from ai_core.events.event_bus import event_bus
from ai_core.runtime.provenance import ExecutionProvenanceRecorder
from ai_core.tools.runtime_tool_registry import RuntimeToolRegistry
from ai_core.modules.module_builder import RuntimeModuleBuilder
from ai_core.modules.module_loader import RuntimeModuleLoader
from ai_core.modules.autonomous_codegen_executor import AutonomousCodegenExecutor
from ai_core.modules.module_artifact_generator import RuntimeModuleArtifactGenerator
from ai_core.modules.runtime_generated_module_installer import RuntimeGeneratedModuleInstaller
from ai_core.workflow.workflow_normalizer import WorkflowNormalizer
from ai_core.workflow.intent_contract import IntentContractGuard
from ai_core.workflow.planning_recovery import PlanningRecoveryService
from ai_core.workflow.execution_state_repair import ExecutionStateRepair
from ai_core.tools.generic_tool_runner import GenericToolRunner
from ai_core.tools.runtime_tool_artifact_generator import RuntimeToolArtifactGenerator
from ai_core.tools.runtime_generated_tool_installer import RuntimeGeneratedToolInstaller
from ai_core.tools.generic_web_extract_artifact import GenericWebExtractArtifactFactory
from ai_core.research.api_discovery import ApiDiscoveryEngine
from ai_core.research.external_solution_discovery import ExternalSolutionDiscoveryEngine
from ai_core.sandbox.verified_sandbox_runtime import VerifiedSandboxRuntime
from ai_core.execution.state_consistency_validator import ExecutionStateConsistencyValidator
from ai_core.execution.result_classifier import ResultClassifier
from ai_core.execution.candidate_extractor import CandidateExtractor
from ai_core.execution.candidate_strategy_scorer import CandidateStrategyScorer
from ai_core.execution.capability_resolution_decision import CapabilityResolutionDecision
from ai_core.execution.evidence_quality_validator import EvidenceQualityValidator
from ai_core.execution.candidate_result_synthesizer import CandidateResultSynthesizer
from ai_core.execution.runtime_strategy_memory import RuntimeStrategyMemory
from ai_core.execution.provider_reliability import ProviderReliabilityTracker
from ai_core.execution.generated_result_verifier import GeneratedResultVerifier
from ai_core.execution.evidence_direct_answer import EvidenceDirectAnswerBuilder
from ai_core.execution.execution_continuation_coordinator import ExecutionContinuationCoordinator
from ai_core.execution.answer_sufficiency_evaluator import AnswerSufficiencyEvaluator
from ai_core.execution.evidence_satisfied_short_circuit import EvidenceSatisfiedShortCircuit
from ai_core.runtime.capability.capability_router import CapabilityRouter
from ai_core.research.web_research_tool import GenericWebResearchTool
from ai_core.context.evidence_noise_reducer import EvidenceNoiseReducer
from ai_core.knowledge.knowledge_service import KnowledgeService
from ai_core.utils.safe_json import make_json_safe
from ai_core.runtime.governance import RuntimeCostPolicy
from ai_core.runtime.evidence import EvidenceBudgetAllocator, CandidateEvidenceRanker, AdaptiveEvidenceReducer
from ai_core.execution.execution_method_contract import ExecutionMethodContract, ExecutionMethodProposalEngine, ExecutionMethodResolver
from ai_core.research.deep_web_research import DeepWebResearchPipeline
from ai_core.research.structured_provider_executor import StructuredProviderExecutor
from ai_core.llm.provider_router import ProviderRouter
from ai_core.config.paths import PROJECT_ROOT, RUNTIME_GENERATED, RUNTIME_REGISTRY


class ToolCallExecutor:
    """
    Generic tool-call executor.

    It does not know any business/domain-specific concepts. It reads the
    runtime-generated workflow plan, normalizes generic fields, resolves tool
    availability by capability metadata, and returns a continuation-aware
    execution state.
    """

    def __init__(self) -> None:
        self.tool_registry = RuntimeToolRegistry()
        self.module_builder = RuntimeModuleBuilder()
        self.module_loader = RuntimeModuleLoader()
        self.autonomous_codegen = AutonomousCodegenExecutor()
        self.module_artifact_generator = RuntimeModuleArtifactGenerator()
        self.module_installer = RuntimeGeneratedModuleInstaller()
        self.normalizer = WorkflowNormalizer()
        self.intent_contract_guard = IntentContractGuard()
        self.planning_recovery = PlanningRecoveryService()
        self.execution_state_repair = ExecutionStateRepair()
        self.tool_runner = GenericToolRunner()
        self.artifact_generator = RuntimeToolArtifactGenerator()
        self.artifact_installer = RuntimeGeneratedToolInstaller()
        self.provenance = ExecutionProvenanceRecorder()
        self.api_discovery = ApiDiscoveryEngine()
        self.external_discovery = ExternalSolutionDiscoveryEngine()
        self.sandbox_verifier = VerifiedSandboxRuntime()
        self.state_consistency = ExecutionStateConsistencyValidator()
        self.result_classifier = ResultClassifier()
        self.candidate_extractor = CandidateExtractor()
        self.candidate_scorer = CandidateStrategyScorer()
        self.capability_resolution = CapabilityResolutionDecision()
        self.generic_web_extract_factory = GenericWebExtractArtifactFactory()
        self.evidence_quality = EvidenceQualityValidator()
        self.candidate_synthesizer = CandidateResultSynthesizer()
        self.strategy_memory = RuntimeStrategyMemory()
        self.provider_reliability = ProviderReliabilityTracker()
        self.evidence_direct_answer = EvidenceDirectAnswerBuilder()
        self.evidence_noise_reducer = EvidenceNoiseReducer()
        self.knowledge = KnowledgeService()
        self.generated_result_verifier = GeneratedResultVerifier()
        self.execution_continuation = ExecutionContinuationCoordinator()
        self.answer_sufficiency = AnswerSufficiencyEvaluator()
        self.web_research = GenericWebResearchTool()
        self.evidence_short_circuit = EvidenceSatisfiedShortCircuit()
        self.capability_router = CapabilityRouter()
        self.runtime_cost_policy = RuntimeCostPolicy()
        self.evidence_budget_allocator = EvidenceBudgetAllocator()
        self.candidate_evidence_ranker = CandidateEvidenceRanker()
        self.adaptive_evidence_reducer = AdaptiveEvidenceReducer()
        self.execution_method_proposer = ExecutionMethodProposalEngine()
        self.execution_method_resolver = ExecutionMethodResolver()
        self.deep_web_research = DeepWebResearchPipeline()
        self.structured_provider_executor = StructuredProviderExecutor()
        self.provider_router = ProviderRouter()

    async def execute(
        self,
        workflow_node: dict[str, Any],
        node_config: dict[str, Any],
        state: dict[str, Any],
        capability_result: dict[str, Any],
    ) -> dict[str, Any]:
        return await self.run(
            run_id=state.get("run_id", ""),
            node_id=node_config.get("node_id") or workflow_node.get("id", "execution"),
            node_config=node_config,
            state=state,
            capability_result=capability_result,
        )

    async def run(
        self,
        *,
        run_id: str,
        node_id: str,
        node_config: dict[str, Any],
        state: dict[str, Any],
        capability_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        previous_results = state.get("results", {})
        validation_result = previous_results.get("pre_execution_validation") if isinstance(previous_results.get("pre_execution_validation"), dict) else {}
        validation_payload = validation_result.get("validation_record") if isinstance(validation_result.get("validation_record"), dict) else validation_result
        if validation_payload and validation_payload.get("status") != "passed":
            interaction_requests = self._interaction_requests_from_validation(validation_payload)
            waiting_for_input = bool(interaction_requests)
            return {
                "_executor_type": "tool_call",
                "_node_id": node_id,
                "status": "waiting_for_human_information" if waiting_for_input else "blocked",
                "message": "Execution is waiting for runtime input before the locked action can run." if waiting_for_input else "Execution stopped because pre_execution_validation did not pass. Repair loop must regenerate planning/preparation/validation before execution.",
                "execution_steps": [],
                "blocked_steps": [{
                    "step_id": "pre_execution_validation",
                    "status": "waiting_for_runtime_input" if waiting_for_input else "validation_failed",
                    "reason": "Runtime parameter input is required before execution." if waiting_for_input else "pre_execution_validation.status must be passed before execution.",
                    "validation_record": validation_payload,
                    "ui_requests": interaction_requests,
                }],
                "human_interactions": interaction_requests,
                "missing_tools": [],
                "safety_holds": [],
                "repair_instruction": {
                    "target_stage": "requirement_completion" if waiting_for_input else "feedback_repair",
                    "retry_from": "pre_execution_validation" if waiting_for_input else "workflow_planning",
                    "max_repair_attempts": 3,
                    "required_result": "user supplies runtime parameters and pre_execution_validation.status == passed" if waiting_for_input else "pre_execution_validation.status == passed",
                },
            }
        workflow_plan = previous_results.get("agent_action_planning", {}) or previous_results.get("workflow_planning", {})
        if isinstance(workflow_plan, dict) and isinstance(workflow_plan.get("action_planning_record"), dict):
            workflow_plan = workflow_plan.get("action_planning_record")
        normalized_plan = self.normalizer.normalize(workflow_plan)
        normalized_plan = self.planning_recovery.recover_if_empty(
            workflow_plan=normalized_plan,
            user_input=state.get("input", ""),
            previous_results=previous_results,
        )
        normalized_plan = self.execution_state_repair.repair(
            normalized_plan,
            runtime_context=state.get("runtime_context") if isinstance(state.get("runtime_context"), dict) else {},
        )
        normalized_plan = self.intent_contract_guard.apply(normalized_plan, previous_results)
        if isinstance(normalized_plan.get("intent_contract"), dict):
            previous_results["intent_contract"] = normalized_plan.get("intent_contract")
            state["intent_contract"] = normalized_plan.get("intent_contract")
        previous_results["workflow_planning"] = normalized_plan
        planned_steps = normalized_plan.get("planned_steps", [])

        await event_bus.emit(run_id, {
            "type": "EXECUTION_PLANNER_STARTED",
            "title": "Execution planner started",
            "message": f"Planning execution for {len(planned_steps)} step(s).",
            "node_id": node_id,
        })

        if not planned_steps:
            return {
                "_executor_type": "tool_call",
                "_node_id": node_id,
                "status": "no_planned_steps",
                "message": "No planned_steps found in workflow_planning result.",
                "execution_steps": [],
                "blocked_steps": [],
                "human_interactions": [],
                "missing_tools": [],
                "safety_holds": [],
                "normalized_workflow": normalized_plan,
            }

        execution_steps: list[dict[str, Any]] = []
        blocked_steps: list[dict[str, Any]] = []
        human_interactions: list[dict[str, Any]] = []
        optional_human_interactions: list[dict[str, Any]] = []
        missing_tools: list[dict[str, Any]] = []
        safety_holds: list[dict[str, Any]] = []
        generated_modules: list[dict[str, Any]] = []
        cost_snapshot = self.runtime_cost_policy.snapshot(state)
        execution_started_at = datetime.now(timezone.utc)

        for index, step in enumerate(planned_steps):
            if self._execution_budget_exhausted(execution_started_at, cost_snapshot.operation_timeout_seconds):
                blocked_steps.append({
                    "step_id": f"step_{index + 1}",
                    "status": "execution_timeout",
                    "reason": "Execution budget was exhausted before this step could start.",
                })
                break
            step_id = str(step.get("step_id") or step.get("task_id") or f"step_{index + 1}")
            # v57: perform a final per-step structural repair immediately before
            # execution decisions. This prevents stale or over-blocked planner output
            # from bypassing the global repair stage. The logic remains generic and
            # only uses runtime-configured structural policies.
            step = self._repair_single_step_before_execution(step, state)
            step = self.state_consistency.repair_step(step)
            if bool(step.get("skip_execution")):
                execution_steps.append({
                    "step_id": step_id,
                    "status": "skipped",
                    "tool": {"id": "contract_skip", "source": "runtime_contract"},
                    "input": {},
                    "result": {
                        "status": "skipped",
                        "data": {"reason": step.get("skip_reason") or "execution was skipped by contract"},
                    },
                    "source_step": step,
                })
                continue
            required_capability = self._capability_name(step.get("required_capability"))
            human_interaction = self._normalize_human_interaction(step.get("human_interaction"))
            execution_ready = bool(step.get("execution_ready", False))
            requires_confirmation = self.state_consistency.should_request_confirmation(step)

            await event_bus.emit(run_id, {
                "type": "EXECUTION_STEP_ANALYZING",
                "title": "Analyzing execution step",
                "message": f"{step_id} / capability={required_capability or 'none'}",
                "node_id": node_id,
                "step_id": step_id,
            })

            missing_fields = self._missing_fields(step)
            if self.state_consistency.should_request_human_information(step, human_interaction):
                fields = human_interaction.get("fields") or missing_fields
                if fields:
                    interaction = {
                        "step_id": step_id,
                        "type": human_interaction.get("type") or "collect_missing_information",
                        "objective": step.get("objective"),
                        "fields": fields,
                        "reason": "Required information is missing or human interaction is required.",
                        "source_step": step,
                    }
                    human_interactions.append(interaction)
                    blocked_steps.append({
                        "step_id": step_id,
                        "status": "missing_required_information",
                        "missing_fields": missing_fields,
                        "reason": interaction["reason"],
                        "source_step": step,
                    })
                    continue
                # Empty interaction contracts are non-actionable and must not
                # pause the workflow. Continue to readiness/capability routing.


            if not execution_ready:
                blocked_steps.append({
                    "step_id": step_id,
                    "status": "not_execution_ready",
                    "reason": "execution_ready is false.",
                    "source_step": step,
                })
                continue

            selected_execution_mode = self.capability_router.select_mode(
                step=step,
                plan=normalized_plan,
                state=state,
                capability=required_capability or "unknown_capability",
            )
            try:
                classifier_result = self.capability_router.selector.classifier.classify(
                    step=step, plan=normalized_plan, state=state, capability=required_capability or "unknown_capability"
                )
            except Exception:
                classifier_result = {}
            early_tool = self.tool_registry.find_by_capability(required_capability) if required_capability else None
            method_proposals = self.execution_method_proposer.propose(
                step=step,
                plan=normalized_plan,
                state=state,
                selected_mode=selected_execution_mode,
                has_existing_tool=bool(early_tool and self._has_executable_implementation(early_tool)),
                classifier_category=str(classifier_result.get("category") or ""),
            )
            # v5.1: execution does not decide the method. The planner LLM in
            # agent_action_planning already selected the fixed action and locked
            # execution_method. The generic resolver may still produce diagnostics,
            # but the effective contract is rebuilt from the locked step.
            resolved_diagnostic = self.execution_method_resolver.resolve(
                proposals=method_proposals,
                step=step,
                policy=self.capability_router.selector.policy_for(
                    step=step, plan=normalized_plan, state=state, capability=required_capability or "unknown_capability"
                ),
            )
            locked_method = str(step.get("execution_method") or "").strip()
            if not locked_method:
                locked_method = resolved_diagnostic.method
            method_contract = ExecutionMethodContract(
                method=locked_method,
                confidence=1.0,
                cost_level=self.execution_method_resolver._cost(locked_method),
                latency_level=self.execution_method_resolver._latency(locked_method),
                input_schema={},
                output_schema={},
                fallback=[],
                reason="locked by agent_action_planning; execution cannot reselect method",
                proposal_source="agent_action_planning",
                decision_source="locked_workflow_contract",
            )
            # v5.6: locked external actions must not be routed to runtime-native
            # observation or unrelated generated tools. Execution follows the
            # selected action and prepared resource bundle only.
            locked_action = str(step.get("action_type") or step.get("execution_action") or "").strip()
            locked_expected_method = self._locked_step_method(step)
            if locked_expected_method and locked_expected_method != method_contract.method:
                method_contract = self._force_method_contract(
                    base=method_contract,
                    method=locked_expected_method,
                    reason="locked_action_method_enforced_before_execution",
                    step=step,
                )
            step["execution_method_decision"] = method_contract.to_dict()
            await event_bus.emit(run_id, {
                "type": "EXECUTION_METHOD_RESOLVED",
                "title": "Execution method resolved",
                "message": method_contract.method,
                "node_id": node_id,
                "step_id": step_id,
                "result": {"contract": method_contract.to_dict(), "diagnostic_proposals": method_proposals, "selected_mode": selected_execution_mode, "method_reselection_disabled": True},
            })

            # If the plan explicitly asks for runtime-native observation, honor it
            # before any generic web/API/model fallback. This is a generic source
            # contract, not a domain-specific shortcut.
            if self._runtime_native_allowed_for_locked_step(step, method_contract.method) and self._step_requests_runtime_native(step, normalized_plan, required_capability or "runtime_current_observation"):
                runtime_native_result = self.capability_router.try_runtime_native(
                    run_id=run_id,
                    node_id=node_id,
                    step_id=step_id,
                    capability=required_capability or "runtime_current_observation",
                    step=step,
                    state=state,
                    plan=normalized_plan,
                ) or self._try_runtime_native_observation(
                    run_id=run_id,
                    node_id=node_id,
                    step_id=step_id,
                    capability=required_capability or "runtime_current_observation",
                    step={**step, "required_source_level": "runtime_native"},
                    state=state,
                    normalized_plan=normalized_plan,
                )
                if runtime_native_result:
                    runtime_result = runtime_native_result.get("result") if isinstance(runtime_native_result.get("result"), dict) else {}
                    runtime_result.setdefault("data", {})["execution_method_contract"] = method_contract.to_dict()
                    execution_steps.append({
                        "step_id": step_id,
                        "status": "executed",
                        "tool": {"id": "runtime_native_observation", "source": "primary_runtime"},
                        "input": runtime_native_result.get("input"),
                        "result": runtime_result,
                        "provenance": runtime_result.get("provenance") if isinstance(runtime_result, dict) else None,
                        "source_step": step,
                        "priority_path": "runtime_native_contract",
                    })
                    continue

            if method_contract.method == "runtime_generated_tool":
                runtime_native_result = None
                if self._runtime_native_allowed_for_locked_step(step, method_contract.method):
                    runtime_native_result = self.capability_router.try_runtime_native(
                        run_id=run_id,
                        node_id=node_id,
                        step_id=step_id,
                        capability=required_capability or "unknown_capability",
                        step=step,
                        state=state,
                        plan=normalized_plan,
                    )
                    if not runtime_native_result and self._step_requests_runtime_native({**step, "required_source_level": "runtime_native"}, normalized_plan, required_capability or "runtime_current_observation"):
                        runtime_native_result = self._try_runtime_native_observation(
                            run_id=run_id,
                            node_id=node_id,
                            step_id=step_id,
                            capability=required_capability or "runtime_current_observation",
                            step={**step, "required_source_level": "runtime_native"},
                            state=state,
                            normalized_plan=normalized_plan,
                        )
                if runtime_native_result:
                    runtime_result = runtime_native_result.get("result") if isinstance(runtime_native_result.get("result"), dict) else {}
                    runtime_result.setdefault("data", {})["execution_method_contract"] = method_contract.to_dict()
                    execution_steps.append({
                        "step_id": step_id,
                        "status": "executed",
                        "tool": {"id": "runtime_native_observation", "source": "primary_runtime"},
                        "input": runtime_native_result.get("input"),
                        "result": runtime_result,
                        "provenance": runtime_result.get("provenance") if isinstance(runtime_result, dict) else None,
                        "source_step": step,
                        "priority_path": "execution_method_runtime_generated_tool",
                    })
                    continue
                generated_tool_result = await self._try_runtime_generated_tool_execution(
                    run_id=run_id,
                    node_id=node_id,
                    step_id=step_id,
                    capability=required_capability or "runtime_generated_tool",
                    step=step,
                    state=state,
                    method_contract=method_contract,
                )
                if generated_tool_result:
                    result_obj = generated_tool_result.get("result") if isinstance(generated_tool_result.get("result"), dict) else {}
                    execution_steps.append({
                        "step_id": step_id,
                        "status": "executed",
                        "tool": generated_tool_result.get("tool"),
                        "input": generated_tool_result.get("input"),
                        "result": result_obj,
                        "provenance": result_obj.get("provenance") if isinstance(result_obj, dict) else None,
                        "source_step": step,
                        "priority_path": "runtime_generated_artifact_contract",
                    })
                    continue
                if not method_contract.fallback:
                    blocked_steps.append({
                        "step_id": step_id,
                        "status": "runtime_artifact_generation_failed",
                        "reason": "The locked generated-artifact action did not produce an executable artifact result.",
                        "execution_method_contract": method_contract.to_dict(),
                        "source_step": step,
                    })
                    continue

            if method_contract.method in {"web_search", "api_call"} and not self._prepared_resource_allows_method(state=state, step_id=step_id, method=method_contract.method):
                blocked_steps.append({
                    "step_id": step_id,
                    "status": "execution_resource_not_prepared",
                    "reason": "The locked workflow method was not approved by execution_preparation.",
                    "execution_method_contract": method_contract.to_dict(),
                    "source_step": step,
                })
                continue

            if method_contract.method in {"web_search", "api_call"}:
                prepared_external_result = await self._execute_prepared_external_resource(
                    run_id=run_id,
                    node_id=node_id,
                    step_id=step_id,
                    method=method_contract.method,
                    step=step,
                    state=state,
                )
                if prepared_external_result:
                    result_obj = prepared_external_result.get("result") if isinstance(prepared_external_result.get("result"), dict) else {}
                    result_obj.setdefault("data", {})["execution_method_contract"] = method_contract.to_dict()
                    execution_steps.append({
                        "step_id": step_id,
                        "status": "executed",
                        "tool": prepared_external_result.get("tool"),
                        "input": prepared_external_result.get("input"),
                        "result": result_obj,
                        "provenance": (result_obj or {}).get("provenance") if isinstance(result_obj, dict) else None,
                        "source_step": step,
                        "priority_path": "prepared_external_resource_contract",
                    })
                    continue
                routed_web_result = await self._try_strategy_web_evidence_execution(
                    run_id=run_id,
                    node_id=node_id,
                    step_id=step_id,
                    capability=required_capability or "generic_information_access",
                    step=step,
                    state=state,
                    reason="execution_method_" + method_contract.method,
                )
                if routed_web_result:
                    result_obj = routed_web_result.get("result") if isinstance(routed_web_result.get("result"), dict) else {}
                    result_obj.setdefault("data", {})["execution_method_contract"] = method_contract.to_dict()
                    execution_steps.append({
                        "step_id": step_id,
                        "status": "executed",
                        "tool": routed_web_result.get("tool"),
                        "input": routed_web_result.get("input"),
                        "result": result_obj,
                        "provenance": (result_obj or {}).get("provenance") if isinstance(result_obj, dict) else None,
                        "source_step": step,
                        "priority_path": "execution_method_" + method_contract.method,
                    })
                    continue
                blocked_steps.append({
                    "step_id": step_id,
                    "status": "locked_external_execution_failed",
                    "reason": "The locked external execution method did not return verified material; execution must not fall through to registry modules or unrelated runtime tools.",
                    "execution_method_contract": method_contract.to_dict(),
                    "source_step": step,
                    "repair_instruction": {
                        "retry_from": "agent_action_planning",
                        "required_result": "prepare a valid target/endpoint or choose another fixed action explicitly",
                    },
                })
                continue

            if method_contract.method not in {"web_search", "api_call", "knowledge_base", "model_knowledge", "content_generation", "existing_tool", "runtime_generated_tool", "shell", "human_interaction", "no_op", "external_skill", "static_response", "uploaded_artifact"}:
                blocked_steps.append({
                    "step_id": step_id,
                    "status": "unsupported_execution_method",
                    "execution_method_contract": method_contract.to_dict(),
                    "source_step": step,
                })
                continue

            if method_contract.method not in {"web_search", "api_call"}:
                # The resolver did not choose external evidence. Do not let a
                # generic strategy fallback silently change the source contract.
                strategy = []
            else:
                strategy = self._execution_strategy(step, normalized_plan)

            if method_contract.method == "runtime_generated_tool":
                generated_tool_result = await self._try_runtime_generated_tool_execution(
                    run_id=run_id,
                    node_id=node_id,
                    step_id=step_id,
                    capability=required_capability or "runtime_generated_tool",
                    step=step,
                    state=state,
                    method_contract=method_contract,
                )
                if generated_tool_result:
                    result_obj = generated_tool_result.get("result") if isinstance(generated_tool_result.get("result"), dict) else {}
                    execution_steps.append({
                        "step_id": step_id,
                        "status": "executed",
                        "tool": generated_tool_result.get("tool"),
                        "input": generated_tool_result.get("input"),
                        "result": result_obj,
                        "provenance": result_obj.get("provenance") if isinstance(result_obj, dict) else None,
                        "source_step": step,
                        "priority_path": "runtime_generated_artifact_contract",
                    })
                    continue
                blocked_steps.append({
                    "step_id": step_id,
                    "status": "runtime_artifact_generation_failed",
                    "reason": "The locked generated-artifact action did not produce an executable artifact result.",
                    "execution_method_contract": method_contract.to_dict(),
                    "source_step": step,
                })
                continue

            if method_contract.method == "uploaded_artifact":
                uploaded_result = await self._execute_uploaded_artifact(
                    run_id=run_id,
                    node_id=node_id,
                    step_id=step_id,
                    step=step,
                    state=state,
                )
                if uploaded_result:
                    result_obj = uploaded_result.get("result") if isinstance(uploaded_result.get("result"), dict) else {}
                    result_obj.setdefault("data", {})["execution_method_contract"] = method_contract.to_dict()
                    execution_steps.append({
                        "step_id": step_id,
                        "status": "executed",
                        "tool": uploaded_result.get("tool"),
                        "input": uploaded_result.get("input"),
                        "result": result_obj,
                        "provenance": (result_obj or {}).get("provenance") if isinstance(result_obj, dict) else None,
                        "source_step": step,
                        "priority_path": "uploaded_artifact_contract",
                    })
                    continue
                blocked_steps.append({
                    "step_id": step_id,
                    "status": "uploaded_artifact_execution_failed",
                    "reason": "The locked uploaded artifact action did not return a result. Check artifact contract, required UI parameters, and sandbox compatibility.",
                    "execution_method_contract": method_contract.to_dict(),
                    "source_step": step,
                })
                continue

            if method_contract.method in {"shell", "human_interaction", "no_op"}:
                blocked_steps.append({
                    "step_id": step_id,
                    "status": "prepared_but_not_executed",
                    "reason": "The locked action requires a prepared runtime artifact or user interaction before execution.",
                    "execution_method_contract": method_contract.to_dict(),
                    "source_step": step,
                })
                continue

            if method_contract.method == "content_generation":
                generated_content_result = await self._try_model_generation_execution(
                    run_id=run_id,
                    node_id=node_id,
                    step_id=step_id,
                    capability=required_capability or "content_generation",
                    step=step,
                    state=state,
                )
                if generated_content_result:
                    result_obj = generated_content_result.get("result") if isinstance(generated_content_result.get("result"), dict) else {}
                    data_obj = result_obj.get("data") if isinstance(result_obj.get("data"), dict) else {}
                    answer_material = str(data_obj.get("answer_material") or result_obj.get("answer_material") or "").strip()
                    if answer_material:
                        result_obj.setdefault("answer_material", answer_material)
                        result_obj.setdefault("data", data_obj)["answer_material"] = answer_material
                        execution_steps.append({
                            "step_id": step_id,
                            "status": "executed",
                            "tool": {"id": "llm_content_generation", "source": "model_runtime"},
                            "input": generated_content_result.get("input"),
                            "result": result_obj,
                            "provenance": result_obj.get("provenance") if isinstance(result_obj, dict) else None,
                            "source_step": step,
                            "priority_path": "content_generation_contract",
                        })
                        continue
                blocked_steps.append({
                    "step_id": step_id,
                    "status": "content_generation_failed",
                    "reason": "The locked content generation action did not produce answer_material. Execution must not fall through to runtime observation, prompt contracts, web/API, or unrelated tools.",
                    "execution_method_contract": method_contract.to_dict(),
                    "source_step": step,
                    "repair_instruction": {
                        "retry_from": "execution_preparation",
                        "required_result": "prepare a valid prompt/output contract and execute executor_llm_generation until answer_material exists",
                    },
                })
                continue

            # v70.9 priority layer: local/model knowledge first.
            # If previous successful runtime knowledge already covers the current
            # parameters, answer from local knowledge and avoid web/API/codegen.
            local_knowledge_result = None
            if method_contract.method in {"knowledge_base", "model_knowledge"}:
                local_knowledge_result = await self._try_local_knowledge_execution(
                    run_id=run_id,
                    node_id=node_id,
                    step_id=step_id,
                    capability=required_capability or "unknown_capability",
                    step=step,
                    state=state,
                )
            if local_knowledge_result:
                execution_steps.append({
                    "step_id": step_id,
                    "status": "executed",
                    "tool": {"id": "local_knowledge", "source": "runtime_knowledge"},
                    "input": local_knowledge_result.get("input"),
                    "result": local_knowledge_result.get("result"),
                    "provenance": (local_knowledge_result.get("result") or {}).get("provenance") if isinstance(local_knowledge_result.get("result"), dict) else None,
                    "source_step": step,
                    "priority_path": "local_knowledge_first",
                })
                continue

            # v70.23: strategy-driven execution order.  A workflow step may
            # declare a generic execution_strategy such as
            # ["local_knowledge", "web_evidence", "tool_generation"].  This
            # keeps planning domain-neutral and prevents a stale generated
            # module from blocking direct evidence retrieval.
            if self._strategy_prefers(strategy, "web_evidence", before="tool_generation"):
                web_strategy_result = await self._try_strategy_web_evidence_execution(
                    run_id=run_id,
                    node_id=node_id,
                    step_id=step_id,
                    capability=required_capability or "generic_information_access",
                    step=step,
                    state=state,
                    reason="execution_strategy_web_evidence_before_tool_generation",
                )
                if web_strategy_result:
                    execution_steps.append({
                        "step_id": step_id,
                        "status": "executed",
                        "tool": web_strategy_result.get("tool"),
                        "input": web_strategy_result.get("input"),
                        "result": web_strategy_result.get("result"),
                        "provenance": (web_strategy_result.get("result") or {}).get("provenance") if isinstance(web_strategy_result.get("result"), dict) else None,
                        "source_step": step,
                        "priority_path": "web_evidence_before_tool_generation",
                    })
                    continue

            tool = self.tool_registry.find_by_capability(required_capability) if required_capability else None
            if tool and not self._has_executable_implementation(tool):
                await event_bus.emit(run_id, {
                    "type": "NON_EXECUTABLE_TOOL_RECORD_SKIPPED",
                    "title": "Non-executable tool record skipped",
                    "message": "A registry record matched the capability but did not declare a valid executable implementation.",
                    "node_id": node_id,
                    "step_id": step_id,
                    "result": self._public_tool_spec(tool),
                })
                tool = None
            if not tool and required_capability:
                existing_module = self.module_loader.load_by_capability(required_capability)
                if existing_module is not None:
                    module_input = self._build_tool_input(
                        step=step,
                        run_id=run_id,
                        node_id=node_id,
                        step_id=step_id,
                        user_input=state.get("input", ""),
                    )
                    await event_bus.emit(run_id, {
                        "type": "MODULE_EXECUTION_STARTED",
                        "title": "Runtime module execution started",
                        "message": f"Executing reusable module for capability={required_capability}",
                        "node_id": node_id,
                        "step_id": step_id,
                    })
                    module_record = self.module_loader.registry.find_by_capability(required_capability) or {"module_id": required_capability}
                    trace = self.provenance.start(
                        run_id=run_id,
                        node_id=node_id,
                        step_id=step_id,
                        component_type="runtime_module",
                        component_id=str(module_record.get("module_id") or required_capability),
                        capability=required_capability,
                        input_data=module_input,
                        artifact=module_record,
                    )
                    try:
                        raw_module_result = existing_module.run(module_input)
                        module_result = self._normalize_runtime_execution_result(raw_module_result, source="runtime_module")
                        trace = self.provenance.finish(
                            trace,
                            output=module_result,
                            status="success" if self._is_success_result(module_result) else "error",
                            error=module_result.get("error") if isinstance(module_result, dict) else None,
                        )
                        module_result = self.provenance.attach(module_result, trace)
                    except Exception as exc:
                        module_result = {"status": "error", "error": {"message": str(exc)}, "data": {}, "source": "runtime_module"}
                        trace = self.provenance.finish(trace, output=module_result, status="error", error=module_result.get("error"))
                        module_result = self.provenance.attach(module_result, trace)
                    if isinstance(module_result, dict) and module_result.get("provenance"):
                        await event_bus.emit(run_id, {
                            "type": "EXECUTION_PROVENANCE_RECORDED",
                            "title": "Execution provenance recorded",
                            "message": f"Recorded provenance for step={step_id}",
                            "node_id": node_id,
                            "step_id": step_id,
                            "result": module_result.get("provenance"),
                        })
                    if self._is_success_result(module_result):
                        execution_steps.append({
                            "step_id": step_id,
                            "status": "executed",
                            "module": {"capability": required_capability},
                            "input": module_input,
                            "result": module_result,
                            "provenance": module_result.get("provenance") if isinstance(module_result, dict) else None,
                            "source_step": step,
                        })
                        continue

                    # v70.9: a stale/bad registered module must not be the final stop.
                    # Disable it for routing purposes and continue with the normal
                    # priority chain: local knowledge already checked, then web/evidence,
                    # then codegen only if needed.
                    if isinstance(module_record, dict) and module_record.get("module_id"):
                        self.module_loader.registry.update_status(
                            str(module_record.get("module_id")),
                            "disabled",
                            reason=self._result_error_message(module_result, "Module execution failed."),
                        )
                    await event_bus.emit(run_id, {
                        "type": "REGISTERED_MODULE_DISABLED_FOR_FALLBACK",
                        "title": "Registered module disabled for fallback",
                        "message": "Registered module failed execution; checking web/evidence sufficiency before code generation.",
                        "node_id": node_id,
                        "step_id": step_id,
                        "result": {"module": module_record, "failure": module_result},
                    })
                    # v70.13: a failed registered module must not become the final answer.
                    # Before entering API documentation discovery or codegen, run the answer
                    # sufficiency gate over fresh web evidence. If enough answer material exists,
                    # return a direct evidence answer immediately.
                    module_failure_fallback = await self._try_answer_evidence_fallback_after_module_failure(
                        run_id=run_id,
                        node_id=node_id,
                        step_id=step_id,
                        capability=required_capability or "unknown_capability",
                        step=step,
                        state=state,
                        failed_result=module_result,
                    )
                    if module_failure_fallback:
                        execution_steps.append({
                            "step_id": step_id,
                            "status": "executed",
                            "tool": module_failure_fallback.get("tool"),
                            "input": module_failure_fallback.get("input"),
                            "result": module_failure_fallback.get("result"),
                            "provenance": (module_failure_fallback.get("result") or {}).get("provenance") if isinstance(module_failure_fallback.get("result"), dict) else None,
                            "source_step": step,
                            "fallback_after_module_failure": True,
                        })
                        continue
                    # Do not continue here; let the missing-tool path below run.

            if not tool:
                generated_spec = self.tool_registry.create_missing_tool_spec(
                    capability=required_capability or "unknown_capability",
                    step=step,
                    user_input=state.get("input", ""),
                )

                if self._has_executable_implementation(generated_spec):
                    tool = generated_spec
                    await event_bus.emit(run_id, {
                        "type": "RUNTIME_TOOL_GENERATED_AND_REGISTERED",
                        "title": "Runtime tool generated and registered",
                        "message": f"Generated executable runtime tool for capability={required_capability or 'unknown_capability'}",
                        "node_id": node_id,
                        "step_id": step_id,
                        "result": self._public_tool_spec(generated_spec),
                    })
                else:
                    generated_tool = await self._try_generate_executable_tool(
                        run_id=run_id,
                        node_id=node_id,
                        step_id=step_id,
                        capability=required_capability or "unknown_capability",
                        step=step,
                        state=state,
                    )
                    if generated_tool and generated_tool.get("__direct_execution_result__"):
                        tool_input = self._build_tool_input(
                            step=step, run_id=run_id, node_id=node_id, step_id=step_id, user_input=state.get("input", "")
                        )
                        tool_result = generated_tool.get("result") or {"status": "error", "error": {"message": "Direct evidence result was empty."}}
                        execution_steps.append({
                            "step_id": step_id,
                            "status": "executed" if self._is_success_result(tool_result) else "tool_execution_failed",
                            "tool": {"id": "browser_network_deepsearch", "source": "browser_or_web_structured_evidence"},
                            "input": tool_input,
                            "result": tool_result,
                            "provenance": tool_result.get("provenance") if isinstance(tool_result, dict) else None,
                            "source_step": step,
                        })
                        continue
                    if generated_tool and generated_tool.get("__runtime_blocked__"):
                        tool_input = self._build_tool_input(
                            step=step, run_id=run_id, node_id=node_id, step_id=step_id, user_input=state.get("input", "")
                        )
                        fallback_execution = await self._try_multi_candidate_fallback_execution(
                            run_id=run_id,
                            node_id=node_id,
                            step_id=step_id,
                            capability=required_capability or "unknown_capability",
                            step=step,
                            state=state,
                            failed_tool={"api_discovery": (generated_tool.get("discovery") or {}).get("api_discovery") or {}},
                            failed_result={
                                "status": "error",
                                "error": {"code": generated_tool.get("status", "runtime_generation_blocked"), "message": generated_tool.get("reason", "Runtime tool generation was blocked.")},
                                "data": {},
                            },
                            tool_input=tool_input,
                        )
                        if fallback_execution and fallback_execution.get("status") == "success":
                            tool = fallback_execution.get("tool") or tool
                            tool_result = fallback_execution.get("result") or {"status": "error"}
                            execution_steps.append({
                                "step_id": step_id,
                                "status": "executed" if self._is_success_result(tool_result) else "tool_execution_failed",
                                "tool": self._public_tool_spec(tool) if isinstance(tool, dict) else tool,
                                "input": tool_input,
                                "result": tool_result,
                                "provenance": tool_result.get("provenance") if isinstance(tool_result, dict) else None,
                                "source_step": step,
                            })
                            continue
                        if fallback_execution and fallback_execution.get("status") in {"human_interaction_required", "optional_human_interaction_available"}:
                            interaction = fallback_execution.get("human_interaction") or {}
                            interaction_required = bool(interaction.get("required", fallback_execution.get("status") == "human_interaction_required"))
                            interaction_payload = self._build_credential_interaction_payload(
                                interaction=interaction,
                                step_id=step_id,
                                step=step,
                                required=interaction_required,
                            )
                            if interaction_required:
                                human_interactions.append(interaction_payload)
                            else:
                                optional_human_interactions.append(interaction_payload)
                        blocked_steps.append({
                            "step_id": step_id,
                            "status": generated_tool.get("status", "runtime_discovery_blocked"),
                            "capability": required_capability,
                            "reason": generated_tool.get("reason", "Runtime discovery did not produce enough evidence to generate executable code."),
                            "source_step": step,
                            "discovery": generated_tool.get("discovery"),
                            "fallback_attempts": self._compact_attempts(fallback_execution.get("attempts", [])) if fallback_execution else [],
                        })
                        continue
                    if generated_tool:
                        tool = generated_tool
                    else:
                        module_result = await self._try_generate_executable_module(
                            run_id=run_id,
                            node_id=node_id,
                            step_id=step_id,
                            capability=required_capability or "unknown_capability",
                            step=step,
                            state=state,
                        )
                        if module_result and module_result.get("module"):
                            generated_modules.append({
                                "step_id": step_id,
                                "capability": required_capability,
                                "generated_module": module_result.get("registry_record"),
                            })
                            module_input = self._build_tool_input(
                                step=step, run_id=run_id, node_id=node_id, step_id=step_id, user_input=state.get("input", "")
                            )
                            normalized_module_result = self._normalize_runtime_execution_result(
                                module_result.get("result"), source="runtime_generated_module"
                            )
                            normalized_module_result = self.generated_result_verifier.enforce(
                                normalized_module_result,
                                provenance=normalized_module_result.get("provenance") if isinstance(normalized_module_result, dict) else None,
                                artifact=module_result.get("registry_record") if isinstance(module_result, dict) else None,
                            )
                            if self._is_success_result(normalized_module_result):
                                execution_steps.append({
                                    "step_id": step_id,
                                    "status": "executed",
                                    "module": module_result.get("registry_record"),
                                    "input": module_input,
                                    "result": normalized_module_result,
                                    "provenance": normalized_module_result.get("provenance") if isinstance(normalized_module_result, dict) else None,
                                    "source_step": step,
                                })
                                continue

                            # v70.21: generated/installed modules that fail verification
                            # are not terminal. A generated module is only one candidate;
                            # if it returns synthetic or unverified material, continue with
                            # the generic evidence path before declaring the step blocked.
                            generated_module_fallback = await self._try_answer_evidence_fallback_after_module_failure(
                                run_id=run_id,
                                node_id=node_id,
                                step_id=step_id,
                                capability=required_capability or "unknown_capability",
                                step=step,
                                state=state,
                                failed_result=normalized_module_result,
                            )
                            if generated_module_fallback:
                                execution_steps.append({
                                    "step_id": step_id,
                                    "status": "executed",
                                    "tool": generated_module_fallback.get("tool"),
                                    "input": generated_module_fallback.get("input"),
                                    "result": generated_module_fallback.get("result"),
                                    "provenance": (generated_module_fallback.get("result") or {}).get("provenance") if isinstance(generated_module_fallback.get("result"), dict) else None,
                                    "source_step": step,
                                    "fallback_after_generated_module_rejection": True,
                                })
                                continue

                            execution_steps.append({
                                "step_id": step_id,
                                "status": "module_execution_failed",
                                "module": module_result.get("registry_record"),
                                "input": module_input,
                                "result": normalized_module_result,
                                "provenance": normalized_module_result.get("provenance") if isinstance(normalized_module_result, dict) else None,
                                "source_step": step,
                            })
                            blocked_steps.append({
                                "step_id": step_id,
                                "status": "module_execution_failed",
                                "capability": required_capability,
                                "reason": self._result_error_message(normalized_module_result, "Module execution failed."),
                                "source_step": step,
                                "module_result": normalized_module_result,
                            })
                            continue

                        module_blueprint = self.module_builder.ensure_module_for_capability(
                            capability=required_capability or "unknown_capability",
                            source_step=step,
                            user_input=state.get("input", ""),
                        )
                        generated_modules.append({"step_id": step_id, "capability": required_capability, "generated_module": module_blueprint})

                        # v50: if a reusable module is already registered, the workflow must
                        # immediately re-enter execution instead of pausing on a stale
                        # missing_tool_implementation state. ai_core remains generic here:
                        # it only checks registry/loadability by capability and executes the
                        # declared module entrypoint; it does not know the module domain.
                        if module_blueprint.get("status") == "module_already_registered":
                            executed_module = await self._execute_registered_module(
                                run_id=run_id,
                                node_id=node_id,
                                step_id=step_id,
                                capability=required_capability or "unknown_capability",
                                step=step,
                                state=state,
                                component_type="runtime_registered_module",
                            )
                            if executed_module:
                                module_result = executed_module.get("result", {})
                                module_result = self.generated_result_verifier.enforce(
                                    module_result,
                                    provenance=module_result.get("provenance") if isinstance(module_result, dict) else None,
                                    artifact=executed_module.get("registry_record") if isinstance(executed_module, dict) else None,
                                )
                                execution_steps.append({
                                    "step_id": step_id,
                                    "status": "executed" if self._is_success_result(module_result) else "module_execution_failed",
                                    "module": executed_module.get("registry_record"),
                                    "input": executed_module.get("input"),
                                    "result": module_result,
                                    "provenance": module_result.get("provenance") if isinstance(module_result, dict) else None,
                                    "source_step": step,
                                })
                                if not self._is_success_result(module_result):
                                    module_failure_fallback = await self._try_answer_evidence_fallback_after_module_failure(
                                        run_id=run_id,
                                        node_id=node_id,
                                        step_id=step_id,
                                        capability=required_capability or "unknown_capability",
                                        step=step,
                                        state=state,
                                        failed_result=module_result,
                                    )
                                    if module_failure_fallback:
                                        execution_steps.append({
                                            "step_id": step_id,
                                            "status": "executed",
                                            "tool": module_failure_fallback.get("tool"),
                                            "input": module_failure_fallback.get("input"),
                                            "result": module_failure_fallback.get("result"),
                                            "provenance": (module_failure_fallback.get("result") or {}).get("provenance") if isinstance(module_failure_fallback.get("result"), dict) else None,
                                            "source_step": step,
                                            "fallback_after_module_failure": True,
                                        })
                                    else:
                                        blocked_steps.append({
                                            "step_id": step_id,
                                            "status": "module_execution_failed",
                                            "capability": required_capability,
                                            "reason": self._result_error_message(module_result, "Module execution failed."),
                                            "source_step": step,
                                            "module_result": module_result,
                                        })
                                continue

                            # v70.8: a stale registered/blueprint module must not block the workflow.
                            # Try autonomous self-healing: reuse the original codegen request when present,
                            # otherwise use the latest pending request for the capability. If successful,
                            # execute the repaired module immediately.
                            await event_bus.emit(run_id, {
                                "type": "MODULE_SELF_HEALING_STARTED",
                                "title": "Module self-healing started",
                                "message": f"Registered module for capability={required_capability} is not executable. Trying regeneration/fallback.",
                                "node_id": node_id,
                                "step_id": step_id,
                                "result": {"module_blueprint": module_blueprint},
                            })
                            healed_codegen = await self._try_autonomous_codegen_and_execute(
                                run_id=run_id,
                                node_id=node_id,
                                step_id=step_id,
                                capability=required_capability or "unknown_capability",
                                step=step,
                                state=state,
                                module_blueprint=module_blueprint,
                            )
                            if healed_codegen and healed_codegen.get("execution"):
                                healed_execution = healed_codegen.get("execution", {})
                                healed_result = healed_execution.get("result", {})
                                execution_steps.append({
                                    "step_id": step_id,
                                    "status": "executed" if self._is_success_result(healed_result) else "module_execution_failed",
                                    "module": healed_codegen.get("registry_record") or healed_execution.get("registry_record"),
                                    "input": healed_execution.get("input"),
                                    "result": healed_result,
                                    "provenance": healed_result.get("provenance") if isinstance(healed_result, dict) else None,
                                    "source_step": step,
                                    "self_healed": True,
                                })
                                if not self._is_success_result(healed_result):
                                    blocked_steps.append({
                                        "step_id": step_id,
                                        "status": "module_execution_failed",
                                        "capability": required_capability,
                                        "reason": self._result_error_message(healed_result, "Self-healed module execution failed."),
                                        "source_step": step,
                                        "module_result": healed_result,
                                    })
                                continue

                            # If regeneration could not execute, keep going into the generic missing-tool path
                            # rather than returning registered_module_not_executable as the final answer.
                            await event_bus.emit(run_id, {
                                "type": "MODULE_SELF_HEALING_FAILED",
                                "title": "Module self-healing failed",
                                "message": "Registered module could not be repaired automatically; continuing with generic fallback generation.",
                                "node_id": node_id,
                                "step_id": step_id,
                                "result": healed_codegen or {},
                            })

                        # v59: do not stop at a generated codegen request. Try to
                        # execute the pending runtime code-generation request, verify
                        # the result in sandbox, enable the registry record, and then
                        # immediately resume the same step by executing the enabled
                        # module. This remains generic: only request files, manifests,
                        # sandbox status, and capability metadata are used.
                        codegen_result = await self._try_autonomous_codegen_and_execute(
                            run_id=run_id,
                            node_id=node_id,
                            step_id=step_id,
                            capability=required_capability or "unknown_capability",
                            step=step,
                            state=state,
                            module_blueprint=module_blueprint,
                        )
                        if codegen_result and codegen_result.get("execution"):
                            module_result = codegen_result["execution"].get("result", {})
                            execution_steps.append({
                                "step_id": step_id,
                                "status": "executed" if self._is_success_result(module_result) else "module_execution_failed",
                                "module": codegen_result.get("registry_record"),
                                "input": codegen_result["execution"].get("input"),
                                "result": module_result,
                                "provenance": module_result.get("provenance") if isinstance(module_result, dict) else None,
                                "source_step": step,
                                "autonomous_codegen": codegen_result.get("codegen"),
                            })
                            generated_modules.append({
                                "step_id": step_id,
                                "capability": required_capability,
                                "generated_module": codegen_result.get("registry_record"),
                                "autonomous_codegen": codegen_result.get("codegen"),
                            })
                            if not self._is_success_result(module_result):
                                blocked_steps.append({
                                    "step_id": step_id,
                                    "status": "module_execution_failed",
                                    "capability": required_capability,
                                    "reason": self._result_error_message(module_result, "Module execution failed after autonomous codegen."),
                                    "source_step": step,
                                    "module_result": module_result,
                                })
                            continue

                        missing_tools.append({"step_id": step_id, "capability": required_capability, "generated_tool_spec": generated_spec, "generated_module": module_blueprint, "autonomous_codegen": codegen_result})
                        await event_bus.emit(run_id, {
                            "type": "TOOL_AND_MODULE_REQUEST_GENERATED",
                            "title": "Tool/module request generated",
                            "message": f"Generated request for capability={required_capability or 'unknown_capability'}",
                            "node_id": node_id,
                            "step_id": step_id,
                            "result": {"tool": generated_spec, "module": module_blueprint, "autonomous_codegen": codegen_result},
                        })
                        blocked_steps.append({"step_id": step_id, "status": "missing_tool_implementation", "capability": required_capability, "source_step": step})
                        continue

            if self._requires_confirmation(step, tool, state):
                safety_holds.append({
                    "step_id": step_id,
                    "status": "waiting_for_human_confirmation",
                    "reason": "Step or runtime tool policy requires explicit human confirmation.",
                    "source_step": step,
                    "tool": self._public_tool_spec(tool),
                })
                blocked_steps.append({
                    "step_id": step_id,
                    "status": "waiting_for_human_confirmation",
                    "reason": "Human confirmation required by runtime policy.",
                    "source_step": step,
                })
                continue

            tool_input = self._build_tool_input(
                step=step,
                run_id=run_id,
                node_id=node_id,
                step_id=step_id,
                user_input=state.get("input", ""),
            )
            tool_result = self.tool_runner.run_tool(
                tool,
                tool_input,
                run_id=run_id,
                node_id=node_id,
                step_id=step_id,
                capability=required_capability,
            )
            tool_result = self._enforce_evidence_quality(tool_result, tool_input)

            if tool_result.get("status") != "success":
                repaired_tool = await self._try_repair_executable_tool(
                    run_id=run_id,
                    node_id=node_id,
                    step_id=step_id,
                    capability=required_capability or "unknown_capability",
                    step=step,
                    state=state,
                    failed_tool=tool,
                    failed_result=tool_result,
                )
                if repaired_tool:
                    tool = repaired_tool
                    tool_result = self.tool_runner.run_tool(
                        tool,
                        tool_input,
                        run_id=run_id,
                        node_id=node_id,
                        step_id=step_id,
                        capability=required_capability,
                    )
                    tool_result = self._enforce_evidence_quality(tool_result, tool_input)

            if tool_result.get("status") != "success" and self._contract_allows_external_fallback(method_contract):
                fallback_execution = await self._try_multi_candidate_fallback_execution(
                    run_id=run_id,
                    node_id=node_id,
                    step_id=step_id,
                    capability=required_capability or "unknown_capability",
                    step=step,
                    state=state,
                    failed_tool=tool,
                    failed_result=tool_result,
                    tool_input=tool_input,
                )
                if fallback_execution and fallback_execution.get("status") == "success":
                    tool = fallback_execution.get("tool") or tool
                    tool_result = fallback_execution.get("result") or tool_result
                    tool_result.setdefault("fallback_attempts", self._compact_attempts(fallback_execution.get("attempts", [])))
                elif fallback_execution and fallback_execution.get("status") in {"human_interaction_required", "optional_human_interaction_available"}:
                    interaction = fallback_execution.get("human_interaction") or {}
                    interaction_required = bool(interaction.get("required", fallback_execution.get("status") == "human_interaction_required"))
                    interaction_payload = self._build_credential_interaction_payload(
                        interaction=interaction,
                        step_id=step_id,
                        step=step,
                        required=interaction_required,
                    )
                    if interaction_required:
                        human_interactions.append(interaction_payload)
                        tool_result = {
                            "status": "error",
                            "error": {"code": "credential_choice_required", "message": "Credential-protected candidates require a user choice."},
                            "data": {},
                            "source": "multi_candidate_fallback",
                            "requires_human_confirmation": False,
                            "fallback_attempts": self._compact_attempts(fallback_execution.get("attempts", [])),
                        }
                    else:
                        optional_human_interactions.append(interaction_payload)
                        tool_result = {
                            "status": "error",
                            "error": {"code": "optional_credential_available", "message": "A credential-protected candidate is available as an optional upgrade."},
                            "data": {"optional_human_interaction": interaction_payload},
                            "source": "multi_candidate_fallback",
                            "requires_human_confirmation": False,
                            "fallback_attempts": self._compact_attempts(fallback_execution.get("attempts", [])),
                        }
                elif fallback_execution and fallback_execution.get("attempts"):
                    tool_result.setdefault("fallback_attempts", self._compact_attempts(fallback_execution.get("attempts", [])))
            elif tool_result.get("status") != "success":
                tool_result.setdefault("execution_method_contract", method_contract.to_dict())
                tool_result.setdefault("contract_fallback_blocked", not self._contract_allows_external_fallback(method_contract))

            if isinstance(tool_result, dict) and tool_result.get("provenance"):
                await event_bus.emit(run_id, {
                    "type": "EXECUTION_PROVENANCE_RECORDED",
                    "title": "Execution provenance recorded",
                    "message": f"Recorded provenance for step={step_id}",
                    "node_id": node_id,
                    "step_id": step_id,
                    "result": tool_result.get("provenance"),
                })

            execution_steps.append({
                "step_id": step_id,
                "status": "executed" if tool_result.get("status") == "success" else "tool_execution_failed",
                "tool": self._public_tool_spec(tool),
                "input": tool_input,
                "result": tool_result,
                "provenance": tool_result.get("provenance") if isinstance(tool_result, dict) else None,
                "source_step": step,
            })

            if tool_result.get("status") != "success":
                blocked_steps.append({
                    "step_id": step_id,
                    "status": "tool_execution_failed",
                    "reason": tool_result.get("error", {}).get("message") or "Tool execution failed.",
                    "source_step": step,
                    "tool_result": tool_result,
                })

        status = self._overall_status(execution_steps, blocked_steps, human_interactions, missing_tools, safety_holds, optional_human_interactions)
        result = {
            "_executor_type": "tool_call",
            "_node_id": node_id,
            "status": status,
            "execution_steps": execution_steps,
            "blocked_steps": blocked_steps,
            "human_interactions": human_interactions,
            "optional_human_interactions": optional_human_interactions,
            "missing_tools": missing_tools,
            "generated_modules": generated_modules,
            "safety_holds": safety_holds,
            "normalized_workflow": normalized_plan,
            "summary": {
                "planned": len(planned_steps),
                "executed": len([step for step in execution_steps if step.get("status") == "executed"]),
                "failed": len([step for step in execution_steps if step.get("status") in {"tool_execution_failed", "module_execution_failed"}]),
                "blocked": len(blocked_steps),
                "human_interactions": len(human_interactions),
                "optional_human_interactions": len(optional_human_interactions),
                "missing_tools": len(missing_tools),
                "generated_modules": len(generated_modules),
                "safety_holds": len(safety_holds),
            },
        }

        await event_bus.emit(run_id, {
            "type": "EXECUTION_PLANNER_RESULT",
            "title": "Execution planner result",
            "message": f"status={status}, executed={len([step for step in execution_steps if step.get('status') == 'executed'])}, blocked={len(blocked_steps)}",
            "node_id": node_id,
            "result": result,
        })
        return result

    def _locked_step_method(self, step: dict[str, Any]) -> str:
        value = step.get("execution_method") if isinstance(step, dict) else None
        if isinstance(value, str) and value.strip():
            return value.strip()
        action_type = str(step.get("action_type") or step.get("execution_action") or "").strip()
        return {
            "llm_generate": "content_generation",
            "generate_code": "runtime_generated_tool",
            "generate_shell": "shell",
            "call_api_no_key": "api_call",
            "call_api_with_key": "api_call",
            "web_query": "web_search",
            "use_existing_tool": "existing_tool",
            "use_external_skill": "external_skill",
            "use_uploaded_file": "uploaded_artifact",
            "use_local_knowledge": "knowledge_base",
            "generate_complex_tool": "runtime_generated_tool",
            "compose_static_response": "static_response",
            "ask_user": "human_interaction",
            "no_op": "no_op",
        }.get(action_type, "")

    def _runtime_native_allowed_for_locked_step(self, step: dict[str, Any], method: str) -> bool:
        action_type = str((step or {}).get("action_type") or (step or {}).get("execution_action") or "").strip()
        # Runtime-native observation is allowed only when explicitly requested by
        # the locked step/source contract. It must not become a generic fallback
        # for code/tool generation or content generation.
        if method in {"content_generation", "web_search", "api_call", "uploaded_artifact", "existing_tool", "external_skill", "static_response"}:
            return False
        if action_type in {"generate_code", "generate_complex_tool", "generate_shell", "llm_generate"}:
            return False
        text = " ".join(str((step or {}).get(k) or "") for k in ("required_source_level", "source_level", "execution_mode", "execution_method"))
        return "runtime_native" in text or "native_observation" in text or "primary_runtime" in text

    def _force_method_contract(self, *, base: ExecutionMethodContract, method: str, reason: str, step: dict[str, Any]) -> ExecutionMethodContract:
        step_policy = step.get("execution_method_policy") if isinstance(step.get("execution_method_policy"), dict) else {}
        fallback_allowed = bool(step_policy.get("fallback_allowed", False))
        return ExecutionMethodContract(
            method=method,
            confidence=max(float(base.confidence or 0), 0.95),
            cost_level=self.execution_method_resolver._cost(method),
            latency_level=self.execution_method_resolver._latency(method),
            input_schema=base.input_schema,
            output_schema=base.output_schema,
            fallback=list(base.fallback or []) if fallback_allowed else [],
            reason=reason,
            proposal_source=base.proposal_source,
            decision_source="locked_workflow_action_enforcer",
        )

    def _prepared_resource_for_step(self, *, state: dict[str, Any], step_id: str) -> dict[str, Any]:
        results = state.get("results") if isinstance(state, dict) and isinstance(state.get("results"), dict) else {}
        prep = results.get("execution_preparation") if isinstance(results.get("execution_preparation"), dict) else {}
        record = prep.get("execution_preparation_record") if isinstance(prep.get("execution_preparation_record"), dict) else prep
        bundle = record.get("resource_bundle") if isinstance(record.get("resource_bundle"), dict) else {}
        steps = bundle.get("steps") if isinstance(bundle.get("steps"), list) else []
        for item in steps:
            if isinstance(item, dict) and str(item.get("step_id")) == str(step_id):
                return item
        return {}

    def _selected_prepared_external_url(self, *, resource: dict[str, Any], method: str) -> str:
        if method == "api_call":
            api = resource.get("api_call_preparation") if isinstance(resource.get("api_call_preparation"), dict) else {}
            if api.get("credential_interaction_required"):
                return ""
            endpoints = api.get("endpoint_candidates") if isinstance(api.get("endpoint_candidates"), list) else []
            return str(endpoints[0]).strip() if endpoints else ""
        if method == "web_search":
            web = resource.get("web_collection") if isinstance(resource.get("web_collection"), dict) else {}
            if web.get("credential_interaction_required"):
                return ""
            api_contract = web.get("api_contract_from_discovery") if isinstance(web.get("api_contract_from_discovery"), dict) else {}
            selected = str(api_contract.get("selected_endpoint") or "").strip()
            if selected:
                return selected
            targets = web.get("targets") if isinstance(web.get("targets"), list) else []
            return str(targets[0]).strip() if targets else ""
        return ""

    async def _execute_prepared_external_resource(
        self,
        *,
        run_id: str,
        node_id: str,
        step_id: str,
        method: str,
        step: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Execute the exact external URL approved by execution_preparation.

        This is generic and provider-neutral. It does not discover a domain or
        provider. It only executes the locked prepared URL and preserves it as
        evidence/provenance. Credential-required candidates are intentionally
        not executed here; validation should route them to user interaction.
        """
        resource = self._prepared_resource_for_step(state=state, step_id=step_id)
        url = self._selected_prepared_external_url(resource=resource, method=method)
        if not url or not str(url).lower().startswith(("http://", "https://")):
            return None
        await event_bus.emit(run_id, {
            "type": "PREPARED_EXTERNAL_RESOURCE_EXECUTION_STARTED",
            "title": "Prepared external resource execution started",
            "message": "Executing the locked URL prepared by execution_preparation.",
            "node_id": node_id,
            "step_id": step_id,
            "result": {"url": url, "method": method},
        })
        def fetch() -> dict[str, Any]:
            req = urllib.request.Request(url, headers={"User-Agent": "cdac-nesthub-runtime/1.0", "Accept": "application/json,text/plain,*/*"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                status = getattr(resp, "status", 200)
                content_type = resp.headers.get("content-type", "") if hasattr(resp, "headers") else ""
                raw = resp.read(512000)
            text = raw.decode("utf-8", errors="replace")
            parsed: Any = None
            if "json" in content_type.lower() or text.lstrip().startswith(("{", "[")):
                try:
                    parsed = json.loads(text)
                except Exception:
                    parsed = None
            return {"status_code": status, "content_type": content_type, "text": text[:12000], "json": parsed}
        try:
            payload = await asyncio.to_thread(fetch)
        except Exception as exc:
            await event_bus.emit(run_id, {
                "type": "PREPARED_EXTERNAL_RESOURCE_EXECUTION_FAILED",
                "title": "Prepared external resource execution failed",
                "message": str(exc),
                "node_id": node_id,
                "step_id": step_id,
                "result": {"url": url, "method": method},
            })
            return None
        data = {
            "answer_material": payload.get("json") if payload.get("json") is not None else payload.get("text"),
            "normalized_facts": payload.get("json") if isinstance(payload.get("json"), dict) else {},
            "content": payload.get("text"),
            "source_urls": [url],
            "evidence_urls": [url],
            "http_status": payload.get("status_code"),
            "content_type": payload.get("content_type"),
        }
        result = {
            "status": "success" if int(payload.get("status_code") or 0) < 400 else "failed",
            "data": data,
            "provenance": {
                "source": "prepared_external_resource",
                "method": method,
                "source_urls": [url],
                "executed_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        return {"tool": {"id": "prepared_external_resource_executor", "source": "execution_preparation"}, "input": {"url": url, "method": method}, "result": result}

    def _interaction_requests_from_validation(self, validation_payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract UI/runtime input requests from validation output.

        pre_execution_validation is allowed to block execution when a locked
        action has a prepared UI request (for example, missing runtime
        parameters for an uploaded artifact or an optional credential prompt).
        Execution must return that request to the UI instead of raising an
        AttributeError or running an unrelated fallback.
        """
        if not isinstance(validation_payload, dict):
            return []
        checks = validation_payload.get("checks") if isinstance(validation_payload.get("checks"), list) else []
        requests: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in checks:
            if not isinstance(item, dict):
                continue
            req = item.get("ui_request") if isinstance(item.get("ui_request"), dict) else None
            if not req:
                continue
            payload = dict(req)
            payload.setdefault("step_id", item.get("step_id"))
            payload.setdefault("required", True)
            payload.setdefault("type", payload.get("type") or "collect_runtime_parameters")
            payload.setdefault("title", payload.get("title") or "Additional input required")
            payload.setdefault("message", payload.get("message") or "Please provide the required runtime input values and resume the workflow.")
            key = json.dumps(payload, sort_keys=True, default=str)
            if key in seen:
                continue
            seen.add(key)
            requests.append(payload)
        return requests

    async def _execute_uploaded_artifact(
        self,
        *,
        run_id: str,
        node_id: str,
        step_id: str,
        step: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any] | None:
        resource = self._prepared_resource_for_step(state=state, step_id=step_id)
        contract = resource.get("uploaded_artifact_execution") if isinstance(resource.get("uploaded_artifact_execution"), dict) else {}
        if not contract or not contract.get("approved_in_preparation"):
            return None
        artifact = contract.get("selected_artifact") if isinstance(contract.get("selected_artifact"), dict) else {}
        resolved_path = str(artifact.get("resolved_path") or "").strip()
        if not resolved_path:
            return None
        path = Path(resolved_path)
        try:
            project = PROJECT_ROOT.resolve()
            resolved = path.resolve()
            allowed_roots = (project, Path("/mnt/data").resolve())
            if not any(str(resolved).startswith(str(root)) for root in allowed_roots):
                return None
        except Exception:
            return None
        known = contract.get("known_parameter_values") if isinstance(contract.get("known_parameter_values"), dict) else {}
        known = self._normalize_uploaded_artifact_call_values(known)
        entry = artifact.get("execution_entrypoint") if isinstance(artifact.get("execution_entrypoint"), dict) else {}
        suffix = path.suffix.lower()
        await event_bus.emit(run_id, {
            "type": "UPLOADED_ARTIFACT_EXECUTION_STARTED",
            "title": "Uploaded artifact execution started",
            "message": "Executing the locked uploaded artifact in sandbox-compatible mode.",
            "node_id": node_id,
            "step_id": step_id,
            "result": {"path": str(path), "entrypoint": entry},
        })
        try:
            if suffix == ".py":
                payload = await asyncio.to_thread(self._run_uploaded_python_artifact, path, entry, known)
            else:
                payload = {"status": "success", "output": path.read_text(encoding="utf-8", errors="replace")[:12000]}
        except Exception as exc:
            await event_bus.emit(run_id, {
                "type": "UPLOADED_ARTIFACT_EXECUTION_FAILED",
                "title": "Uploaded artifact execution failed",
                "message": str(exc),
                "node_id": node_id,
                "step_id": step_id,
                "result": {"path": str(path)},
            })
            return None
        result = {
            "status": "success" if payload.get("status") == "success" else "failed",
            "data": {
                "answer_material": payload.get("output"),
                "normalized_facts": payload.get("normalized_facts") if isinstance(payload.get("normalized_facts"), dict) else {},
                "content": payload.get("output"),
                "artifact_path": str(path),
                "artifact_contract": contract,
            },
            "provenance": {
                "source": "uploaded_artifact",
                "artifact_path": str(path),
                "executed_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        return {"tool": {"id": "uploaded_artifact_executor", "source": "execution_preparation"}, "input": {"artifact_path": str(path), "parameters": known}, "result": result}

    def _normalize_uploaded_artifact_call_values(self, values: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        if not isinstance(values, dict):
            return normalized
        for key, value in values.items():
            # Keep list values intact. Whether a callable expects a list is
            # determined by its own signature contract and by the UI field type,
            # not by a hard-coded single-value collapse.
            normalized[str(key)] = value
        return normalized

    def _run_uploaded_python_artifact(self, path: Path, entry: dict[str, Any], known: dict[str, Any]) -> dict[str, Any]:
        module_name = f"uploaded_artifact_{abs(hash(str(path)))}"
        spec = importlib.util.spec_from_file_location(module_name, str(path))
        if spec is None or spec.loader is None:
            raise RuntimeError("unable_to_load_uploaded_python_artifact")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        function_name = str(entry.get("function") or "run")
        func = getattr(module, function_name, None)
        if not callable(func):
            raise RuntimeError("uploaded_python_artifact_has_no_callable_entrypoint")
        sig = inspect.signature(func)
        stdout_buffer = io.StringIO()
        with contextlib.redirect_stdout(stdout_buffer):
            if len(sig.parameters) == 1 and next(iter(sig.parameters.keys())) in {"payload", "input", "data", "params"}:
                value = func(dict(known))
            else:
                kwargs = {name: known.get(name) for name in sig.parameters.keys() if name in known}
                value = func(**kwargs)
        stdout_text = stdout_buffer.getvalue().strip()
        if isinstance(value, dict):
            output = value.get("answer_material") or value.get("output") or value.get("result") or stdout_text or value
            normalized = dict(value)
            if stdout_text:
                normalized.setdefault("stdout", stdout_text)
            return {"status": "success", "output": output, "normalized_facts": normalized}
        output = value if value not in (None, "", [], {}) else stdout_text
        return {"status": "success" if output not in (None, "", [], {}) else "failed", "output": output, "stdout": stdout_text}

    def _prepared_resource_allows_method(self, *, state: dict[str, Any], step_id: str, method: str) -> bool:
        results = state.get("results") if isinstance(state, dict) and isinstance(state.get("results"), dict) else {}
        prep = results.get("execution_preparation") if isinstance(results.get("execution_preparation"), dict) else {}
        record = prep.get("execution_preparation_record") if isinstance(prep.get("execution_preparation_record"), dict) else prep
        bundle = record.get("resource_bundle") if isinstance(record.get("resource_bundle"), dict) else {}
        steps = bundle.get("steps") if isinstance(bundle.get("steps"), list) else []
        if not steps:
            return method not in {"web_search", "api_call", "uploaded_artifact"}
        for item in steps:
            if not isinstance(item, dict):
                continue
            if str(item.get("step_id")) != str(step_id):
                continue
            if str(item.get("execution_method") or "") != method:
                return False
            if method == "uploaded_artifact":
                contract = item.get("uploaded_artifact_execution") if isinstance(item.get("uploaded_artifact_execution"), dict) else {}
                return bool(contract.get("approved_in_preparation"))
            if method == "web_search":
                web = item.get("web_collection") if isinstance(item.get("web_collection"), dict) else {}
                if web.get("credential_interaction_required"):
                    return False
                api_contract = web.get("api_contract_from_discovery") if isinstance(web.get("api_contract_from_discovery"), dict) else {}
                return bool(web.get("required") and web.get("approved_in_preparation") and (web.get("targets") or api_contract.get("selected_endpoint")))
            if method == "api_call":
                api = item.get("api_call_preparation") if isinstance(item.get("api_call_preparation"), dict) else {}
                if api.get("credential_interaction_required"):
                    return False
                return bool(api.get("required") and api.get("approved_in_preparation") and api.get("endpoint_candidates"))
            return True
        return False

    def _enforce_intent_execution_contract(
        self,
        *,
        method_contract: ExecutionMethodContract,
        step: dict[str, Any],
        plan: dict[str, Any],
        state: dict[str, Any],
    ) -> ExecutionMethodContract:
        """Final runtime guard between planning and execution.

        This is the last deterministic checkpoint. It keeps downstream tool
        execution from bypassing the locked upstream intent contract. The logic
        is generic: it only reads the contract family and method policy.
        """
        locked_method = self._locked_step_method(step)
        if locked_method and locked_method != method_contract.method:
            return self._force_method_contract(
                base=method_contract,
                method=locked_method,
                reason="locked_workflow_action_method_enforced",
                step=step,
            )

        contract = {}
        if isinstance(plan.get("intent_contract"), dict):
            contract = plan.get("intent_contract") or {}
        elif isinstance(state.get("intent_contract"), dict):
            contract = state.get("intent_contract") or {}
        family = str(contract.get("intent_family") or "")
        step_policy = step.get("execution_method_policy") if isinstance(step.get("execution_method_policy"), dict) else {}
        disabled = {str(x) for x in step_policy.get("disabled_methods", []) if str(x).strip()}
        preferred = [str(x) for x in step_policy.get("preferred_methods", []) if str(x).strip()]

        forced = ""
        reason = ""
        if self._step_has_runtime_native_temporal_contract(step=step, contract=contract):
            forced = "runtime_generated_tool"
            reason = "runtime_native_temporal_contract_enforced"
            family = "runtime_observation"
        elif family == "external_information" and method_contract.method in {"runtime_generated_tool", "model_knowledge", "web_search"}:
            # API-first contract: for external structured observations, the runtime must first
            # attempt configured/API-discovered structured providers. Web evidence is only a fallback.
            forced = next((m for m in ["api_call", "existing_tool", "web_search"] if m in preferred and m not in disabled), "api_call")
            reason = "api_first_external_information_contract"
        elif family == "runtime_observation" and method_contract.method in {"web_search", "api_call", "knowledge_base", "model_knowledge"}:
            forced = next((m for m in preferred if m not in disabled and m in {"runtime_generated_tool", "existing_tool"}), "runtime_generated_tool")
            reason = "locked_runtime_observation_contract_blocked_external_method"
        elif method_contract.method in disabled:
            forced = next((m for m in preferred if m not in disabled), "content_generation")
            reason = "method_disabled_by_step_policy"

        if not forced:
            return method_contract

        fallback_allowed = bool(step_policy.get("fallback_allowed", bool(method_contract.fallback)))
        if family == "runtime_observation":
            fallback_allowed = False
        fallback = list(method_contract.fallback or []) if fallback_allowed else []
        return ExecutionMethodContract(
            method=forced,
            confidence=max(float(method_contract.confidence or 0), 0.91),
            cost_level=self.execution_method_resolver._cost(forced),
            latency_level=self.execution_method_resolver._latency(forced),
            input_schema=method_contract.input_schema,
            output_schema=method_contract.output_schema,
            fallback=fallback,
            reason=reason,
            proposal_source=method_contract.proposal_source,
            decision_source="intent_contract_enforcer",
        )


    def _step_has_runtime_native_temporal_contract(self, *, step: dict[str, Any], contract: dict[str, Any]) -> bool:
        """Detect generic runtime-native temporal observations.

        This is not a domain rule. It only checks whether the planner already
        supplied a concrete timestamp-like value as a runtime parameter. In that
        case the runtime can answer from its native state and must not browse
        external pages for the same value.
        """
        values: list[Any] = []
        params = step.get("parameters") if isinstance(step.get("parameters"), dict) else {}
        for section_name in ("known", "optional"):
            section = params.get(section_name) if isinstance(params.get(section_name), dict) else {}
            for key, value in section.items():
                key_text = str(key or "").casefold()
                if "datetime" in key_text or "timestamp" in key_text:
                    values.append(value)
        for value in contract.get("target_values") or []:
            values.append(value)
        import re
        iso_datetime = re.compile(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}T\d{1,2}:\d{2}")
        has_timestamp = any(iso_datetime.search(str(v or "")) for v in values)
        if not has_timestamp:
            return False
        # If the same step has concrete non-temporal external parameters, let the
        # external-information contract handle it. Field names are generic.
        known = params.get("known") if isinstance(params.get("known"), dict) else {}
        non_temporal_keys = [k for k in known.keys() if "datetime" not in str(k).casefold() and "timestamp" not in str(k).casefold() and "timezone" not in str(k).casefold()]
        return len(non_temporal_keys) == 0

    def _contract_allows_external_fallback(self, method_contract: ExecutionMethodContract) -> bool:
        allowed = set(method_contract.fallback or [])
        return bool(allowed.intersection({"web_search", "api_call"}))

    async def _try_autonomous_codegen_and_execute(
        self,
        *,
        run_id: str,
        node_id: str,
        step_id: str,
        capability: str,
        step: dict[str, Any],
        state: dict[str, Any],
        module_blueprint: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Generate, sandbox-verify, enable, and execute a pending module.

        v59 continuation bridge. The executor first looks for the concrete
        codegen request emitted by the module builder. If present, it invokes the
        autonomous codegen runner. If successful, it reloads the enabled module
        and executes the original step without another user action.
        """
        request_path = self._codegen_request_path(module_blueprint or {})
        module_input = self._build_tool_input(
            step=step,
            run_id=run_id,
            node_id=node_id,
            step_id=step_id,
            user_input=state.get("input", ""),
        )
        try:
            if request_path:
                codegen = await self.autonomous_codegen.execute_request_file(
                    request_path=request_path,
                    run_id=run_id,
                    node_id=node_id,
                    step_id=step_id,
                    test_input=module_input,
                )
            else:
                codegen = await self.autonomous_codegen.execute_latest_pending_for_capability(
                    capability=capability,
                    run_id=run_id,
                    node_id=node_id,
                    step_id=step_id,
                    test_input=module_input,
                )
        except Exception as exc:
            await event_bus.emit(run_id, {
                "type": "AUTONOMOUS_CODEGEN_FAILED",
                "title": "Autonomous codegen failed",
                "message": str(exc),
                "node_id": node_id,
                "step_id": step_id,
            })
            return {"status": "autonomous_codegen_failed", "error": {"message": str(exc)}}

        if not codegen or not codegen.get("enabled"):
            return codegen if isinstance(codegen, dict) else None

        executed = await self._execute_registered_module(
            run_id=run_id,
            node_id=node_id,
            step_id=step_id,
            capability=capability,
            step=step,
            state=state,
            component_type="runtime_autonomous_codegen_module",
        )
        if not executed:
            return {"status": "enabled_module_not_executable", "codegen": codegen}

        return {
            "status": "autonomous_codegen_executed",
            "codegen": codegen,
            "registry_record": executed.get("registry_record") or codegen.get("registry_record"),
            "execution": executed,
        }

    def _codegen_request_path(self, module_blueprint: dict[str, Any]) -> str | None:
        if not isinstance(module_blueprint, dict):
            return None
        candidates: list[Any] = []
        candidates.append(module_blueprint.get("codegen_request"))
        generated = module_blueprint.get("generated_module")
        if isinstance(generated, dict):
            candidates.append(generated.get("codegen_request"))
        module = module_blueprint.get("module")
        if isinstance(module, dict):
            metadata = module.get("metadata") if isinstance(module.get("metadata"), dict) else {}
            request_path = metadata.get("codegen_request_path")
            if isinstance(request_path, str) and request_path.strip():
                return request_path
        for item in candidates:
            if isinstance(item, dict):
                path = item.get("request_path")
                if isinstance(path, str) and path.strip():
                    return path
                nested = item.get("request")
                if isinstance(nested, dict):
                    nested_path = nested.get("request_path")
                    if isinstance(nested_path, str) and nested_path.strip():
                        return nested_path
        retu
    async def _try_runtime_generated_tool_execution(
        self,
        *,
        run_id: str,
        node_id: str,
        step_id: str,
        capability: str,
        step: dict[str, Any],
        state: dict[str, Any],
        method_contract: ExecutionMethodContract,
    ) -> dict[str, Any] | None:
        """Generate, persist, map, and execute a runtime source artifact.

        The implementation is domain-neutral. It treats the selected action as a
        request to materialize an executable source artifact, stores the artifact
        in the runtime-generated area, records a reusable agent-to-artifact
        mapping, and executes the artifact in a sandboxed subprocess. It does not
        fall back to runtime observation or unrelated tools.
        """
        tool_input = self._build_tool_input(
            step=step,
            run_id=run_id,
            node_id=node_id,
            step_id=step_id,
            user_input=state.get("input", ""),
        )
        identity = self._runtime_agent_identity(state=state, step=step)
        mapped_path = self._lookup_generated_artifact(identity)
        artifact_reused = False
        if mapped_path and mapped_path.exists():
            artifact_path = mapped_path
            source_code = artifact_path.read_text(encoding="utf-8", errors="ignore")
            artifact_reused = True
        else:
            generated = await self._generate_runtime_source_code(
                run_id=run_id,
                node_id=node_id,
                step_id=step_id,
                step=step,
                state=state,
                tool_input=tool_input,
            )
            source_code = str(generated.get("source_code") or "").strip()
            if not source_code:
                source_code = self._runtime_generated_source_fallback(str(step.get("objective") or state.get("input") or ""))
            artifact_path = self._write_generated_source_artifact(
                run_id=run_id,
                step_id=step_id,
                source_code=source_code,
                identity=identity,
            )
            self._record_generated_artifact_mapping(identity=identity, artifact_path=artifact_path, metadata={
                "run_id": run_id,
                "step_id": step_id,
                "capability": capability,
                "objective": str(step.get("objective") or ""),
                "action_type": str(step.get("action_type") or ""),
                "execution_method": method_contract.method,
            })

        execution = self._execute_python_artifact(artifact_path)
        stdout = str(execution.get("stdout") or "").strip()
        stderr = str(execution.get("stderr") or "").strip()
        answer_material = stdout or stderr or f"Generated artifact executed with return code {execution.get('returncode')}"
        status = "success" if execution.get("returncode") == 0 else "error"
        return {
            "tool": {
                "id": artifact_path.stem,
                "source": "runtime_generated_artifact",
                "path": str(artifact_path),
                "reused_from_agent_mapping": artifact_reused,
            },
            "input": tool_input,
            "result": {
                "status": status,
                "answer_material": answer_material,
                "data": {
                    "answer_material": answer_material,
                    "artifact_path": str(artifact_path),
                    "source_code": source_code,
                    "stdout": self._normalize_generated_process_output(stdout),
                    "stderr": self._normalize_generated_process_output(stderr),
                    "returncode": execution.get("returncode"),
                    "timed_out": execution.get("timed_out", False),
                    "bounded_by_runtime": execution.get("bounded_by_runtime", False),
                    "dependencies": execution.get("dependencies") or [],
                    "agent_artifact_mapping": identity,
                    "execution_method_contract": method_contract.to_dict(),
                },
                "source": "runtime_generated_artifact",
                "requires_human_confirmation": False,
                "provenance": {
                    "source": "runtime_generated_artifact",
                    "artifact_path": str(artifact_path),
                    "execution_claims": {
                        "real_execution_declared": True,
                        "no_mock_data_declared": True,
                        "network_declared": False,
                        "live_verification_passed": status == "success",
                        "evidence_quality_passed": bool(answer_material),
                    },
                },
            },
        }

    async def _generate_runtime_source_code(
        self,
        *,
        run_id: str,
        node_id: str,
        step_id: str,
        step: dict[str, Any],
        state: dict[str, Any],
        tool_input: dict[str, Any],
    ) -> dict[str, Any]:
        objective = str(step.get("objective") or state.get("input") or "").strip()
        known = {}
        if isinstance(tool_input.get("parameters"), dict):
            known.update(tool_input.get("parameters") or {})
        schema = {
            "type": "object",
            "required": ["status", "source_code"],
            "properties": {
                "status": {"type": "string"},
                "source_code": {"type": "string"},
                "entry_command": {"type": "array"},
                "notes": {"type": "string"},
            },
            "additionalProperties": True,
        }
        prompt = {
            "system": (
                "Return JSON only. Generate a safe Python 3 script that satisfies "
                "the objective. Prefer the Python standard library when it is sufficient. "
                "If an external Python package is necessary, import it normally; the runtime "
                "will detect and prepare missing Python packages before execution. "
                "The script must be executable as a standalone file and print its result "
                "to stdout. The script must finish by itself. Do not create unbounded loops, "
                "background daemons, interactive prompts, or waits without a fixed upper bound. "
                "For repeated output, emit a small bounded sample and exit. Do not include markdown fences."
            )
        }
        rendered = (
            "OBJECTIVE=" + objective[:700] +
            "\nPARAMETERS=" + json.dumps(make_json_safe(known), ensure_ascii=False, separators=(",", ":"))[:1200] +
            "\nReturn JSON with source_code containing only Python source text."
        )
        try:
            generated = await self.provider_router.generate_json(
                run_id=run_id,
                node_id="execution",
                adapter={
                    "adapter_id": "runtime_source_generation_adapter",
                    "provider_route": ["ollama", "openai"],
                    "provider_timeout_seconds": 120,
                    "max_provider_attempts": 1,
                    "max_prompt_tokens": 1000,
                    "max_schema_chars": 700,
                    "provider_options": {"temperature": 0.2, "num_predict": 1200, "num_ctx": 2048, "think": False},
                },
                prompt=prompt,
                rendered_user_prompt=rendered,
                schema=schema,
            )
            if isinstance(generated, dict) and str(generated.get("source_code") or "").strip():
                source_code = str(generated.get("source_code") or "").strip()
                if source_code:
                    generated["source_code"] = source_code
                    return generated
        except Exception:
            pass
        # Generic last-resort artifact. It is intentionally domain-neutral and
        # only exposes the runtime timestamp plus the requested objective.
        fallback = self._runtime_generated_source_fallback(objective)
        return {"status": "fallback_generated", "source_code": fallback, "notes": "generic_runtime_timestamp_fallback"}


    @staticmethod
    def _runtime_generated_source_fallback(objective: str) -> str:
        return (
            "from datetime import datetime, timezone\n"
            "def main():\n"
            f"    objective = {objective!r}\n"
            "    now = datetime.now(timezone.utc).astimezone().isoformat()\n"
            "    print(f\"{objective}: {now}\")\n"
            "if __name__ == \"__main__\":\n"
            "    main()\n"
        )

    @classmethod
    def _source_external_imports(cls, source_code: str, *, missing_only: bool = False) -> list[str]:
        """Return non-stdlib top-level imports used by generated source.

        This is a generic dependency detector. It does not decide whether the
        source is acceptable; it only identifies Python modules that may need a
        runtime package preparation step before execution.
        """
        try:
            tree = ast.parse(str(source_code or ""))
        except SyntaxError:
            return []
        stdlib = set(getattr(sys, "stdlib_module_names", set()) or set())
        builtin = set(sys.builtin_module_names)
        allowed = stdlib | builtin | {"__future__"}
        found: list[str] = []
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name.split(".", 1)[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    continue
                if node.module:
                    names = [node.module.split(".", 1)[0]]
            for name in names:
                if not name or name in allowed:
                    continue
                if missing_only and importlib.util.find_spec(name) is not None:
                    continue
                if name not in found:
                    found.append(name)
        return found

    @staticmethod
    def _missing_module_from_stderr(stderr: str) -> str:
        text = str(stderr or "")
        match = re.search(r"ModuleNotFoundError:\s+No module named ['\"]([^'\"]+)['\"]", text)
        if not match:
            match = re.search(r"ImportError:\s+No module named ['\"]([^'\"]+)['\"]", text)
        if not match:
            return ""
        return match.group(1).split(".", 1)[0].strip()

    @staticmethod
    def _runtime_install_allowed() -> bool:
        raw_install = str(__import__("os").environ.get("AI_CORE_ALLOW_INSTALL", "true")).strip().lower()
        raw_network = str(__import__("os").environ.get("AI_CORE_ALLOW_NETWORK_INSTALL", "true")).strip().lower()
        denied = {"0", "false", "no", "off"}
        return raw_install not in denied and raw_network not in denied

    def _prepare_python_dependencies_for_source(self, source_code: str, *, cwd: Path) -> list[dict[str, Any]]:
        """Install missing external Python modules for a generated script.

        The first strategy uses static import detection. A second retry strategy
        in `_execute_python_artifact` handles dynamic imports reported by the
        interpreter. The package name defaults to the missing module name because
        generated runtime artifacts should declare/import installable packages by
        their public import name when possible.
        """
        records: list[dict[str, Any]] = []
        if not self._runtime_install_allowed():
            for module in self._source_external_imports(source_code, missing_only=True):
                records.append({"module": module, "status": "blocked", "reason": "install_not_allowed"})
            return records
        for module in self._source_external_imports(source_code, missing_only=True):
            records.append(self._install_python_module(module, cwd=cwd))
        return records

    def _install_python_module(self, module_name: str, *, cwd: Path) -> dict[str, Any]:
        module = str(module_name or "").split(".", 1)[0].strip()
        if not module:
            return {"module": module, "status": "skipped", "reason": "empty_module"}
        if importlib.util.find_spec(module) is not None:
            return {"module": module, "status": "ready", "changed": False}
        if not self._runtime_install_allowed():
            return {"module": module, "status": "blocked", "reason": "install_not_allowed"}
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "pip", "install", module],
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=300,
            )
            importlib.invalidate_caches()
            ready = importlib.util.find_spec(module) is not None
            return {
                "module": module,
                "status": "ready" if ready else "failed",
                "changed": completed.returncode == 0,
                "returncode": completed.returncode,
                "stdout": (completed.stdout or "")[-4000:],
                "stderr": (completed.stderr or "")[-4000:],
            }
        except Exception as exc:
            return {"module": module, "status": "failed", "error": str(exc)}

    def _write_generated_source_artifact(
        self,
        *,
        run_id: str,
        step_id: str,
        source_code: str,
        identity: dict[str, str],
    ) -> Path:
        safe_name = self._safe_artifact_name(identity.get("agent_name") or identity.get("participant_id") or "runtime_artifact")
        target_dir = RUNTIME_GENERATED / "runtime_artifacts" / safe_name
        target_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = target_dir / f"{safe_name}_{run_id}_{step_id}.py"
        artifact_path.write_text(source_code, encoding="utf-8")
        return artifact_path

    def _normalize_generated_process_output(self, text: str, *, max_lines: int = 12, max_chars: int = 2000) -> str:
        raw = str(text or "")
        if not raw.strip():
            return ""
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if not lines:
            lines = [raw.strip()]
        compact: list[str] = []
        skipped_repeats = 0
        previous = None
        for line in lines:
            if line == previous:
                skipped_repeats += 1
                continue
            previous = line
            compact.append(line)
            if len(compact) >= max_lines:
                break
        result = "\n".join(compact)
        if skipped_repeats:
            result += f"\n...[{skipped_repeats} repeated output lines compacted]"
        if len(result) > max_chars:
            result = result[:max_chars].rstrip() + " ...[truncated]"
        return result

    def _execute_python_artifact(self, artifact_path: Path) -> dict[str, Any]:
        dependency_records: list[dict[str, Any]] = []
        try:
            source_code = artifact_path.read_text(encoding="utf-8", errors="ignore")
            dependency_records.extend(self._prepare_python_dependencies_for_source(source_code, cwd=artifact_path.parent))
        except Exception as exc:
            dependency_records.append({"status": "failed", "stage": "dependency_scan", "error": str(exc)})

        def _decode_timeout_stream(value: Any) -> str:
            if value is None:
                return ""
            if isinstance(value, bytes):
                return value.decode("utf-8", errors="replace")
            return str(value)

        def run_once() -> subprocess.CompletedProcess[str]:
            executable_path = write_bounded_python_copy(artifact_path)
            return subprocess.run(
                [sys.executable, "-u", str(executable_path)],
                cwd=str(executable_path.parent),
                capture_output=True,
                text=True,
                timeout=30,
            )

        try:
            completed = run_once()
            missing_module = self._missing_module_from_stderr(completed.stderr) if completed.returncode != 0 else ""
            if missing_module:
                install_record = self._install_python_module(missing_module, cwd=artifact_path.parent)
                install_record["stage"] = "retry_after_interpreter_error"
                dependency_records.append(install_record)
                if install_record.get("status") == "ready":
                    completed = run_once()
            return {
                "returncode": completed.returncode,
                "stdout": self._normalize_generated_process_output(completed.stdout),
                "stderr": self._normalize_generated_process_output(completed.stderr),
                "dependencies": dependency_records,
                "timed_out": False,
            }
        except subprocess.TimeoutExpired as exc:
            stdout = _decode_timeout_stream(getattr(exc, "stdout", ""))
            stderr = _decode_timeout_stream(getattr(exc, "stderr", ""))
            if stdout.strip():
                return {
                    "returncode": 0,
                    "stdout": self._normalize_generated_process_output(stdout),
                    "stderr": self._normalize_generated_process_output(stderr),
                    "dependencies": dependency_records,
                    "timed_out": True,
                    "bounded_by_runtime": True,
                    "message": "generated_process_stopped_after_timeout_with_output",
                }
            return {
                "returncode": -1,
                "stdout": self._normalize_generated_process_output(stdout),
                "stderr": self._normalize_generated_process_output(stderr or str(exc)),
                "dependencies": dependency_records,
                "timed_out": True,
                "bounded_by_runtime": True,
            }
        except Exception as exc:
            return {"returncode": -1, "stdout": "", "stderr": str(exc), "dependencies": dependency_records, "timed_out": False}

    def _runtime_agent_identity(self, *, state: dict[str, Any], step: dict[str, Any]) -> dict[str, str]:
        previous = state.get("results") if isinstance(state.get("results"), dict) else {}
        input_record = {}
        input_result = previous.get("input_parsing") if isinstance(previous.get("input_parsing"), dict) else {}
        if isinstance(input_result.get("input_record"), dict):
            input_record = input_result.get("input_record") or {}
        context = input_record.get("context") if isinstance(input_record.get("context"), dict) else {}
        return {
            "participant_id": str(context.get("participant_id") or input_record.get("participant_id") or step.get("participant_id") or ""),
            "agent_name": str(input_record.get("participant_name") or context.get("participant_name") or step.get("agent_name") or step.get("participant_name") or ""),
            "objective": str(input_record.get("objective") or step.get("objective") or ""),
        }

    def _mapping_keys_for_identity(self, identity: dict[str, str]) -> list[str]:
        keys = []
        for key in ("participant_id", "agent_name"):
            value = str(identity.get(key) or "").strip()
            if value:
                keys.append(f"{key}:{value}")
        objective = str(identity.get("objective") or "").strip()
        if objective:
            keys.append("objective:" + self._safe_artifact_name(objective)[:80])
        return keys

    def _generated_artifact_map_path(self) -> Path:
        RUNTIME_REGISTRY.mkdir(parents=True, exist_ok=True)
        return RUNTIME_REGISTRY / "generated_artifact_map.json"

    def _load_generated_artifact_map(self) -> dict[str, Any]:
        path = self._generated_artifact_map_path()
        if not path.exists():
            return {"version": 1, "mappings": {}}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("mappings"), dict):
                return data
        except Exception:
            pass
        return {"version": 1, "mappings": {}}

    def _lookup_generated_artifact(self, identity: dict[str, str]) -> Path | None:
        data = self._load_generated_artifact_map()
        mappings = data.get("mappings") if isinstance(data.get("mappings"), dict) else {}
        for key in self._mapping_keys_for_identity(identity):
            item = mappings.get(key)
            if isinstance(item, dict) and item.get("artifact_path"):
                path = Path(str(item.get("artifact_path")))
                if path.exists():
                    return path
        return None

    def _record_generated_artifact_mapping(self, *, identity: dict[str, str], artifact_path: Path, metadata: dict[str, Any]) -> None:
        data = self._load_generated_artifact_map()
        mappings = data.setdefault("mappings", {})
        record = {
            "artifact_path": str(artifact_path),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "identity": identity,
            "metadata": make_json_safe(metadata),
        }
        for key in self._mapping_keys_for_identity(identity):
            mappings[key] = record
        self._generated_artifact_map_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _safe_artifact_name(self, value: str) -> str:
        value = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
        value = value.strip("._-")
        return value[:80] or "runtime_artifact"


    def _executor_generation_instruction(self, *, step: dict[str, Any]) -> str:
        """Build a generic final-deliverable instruction for content generation."""
        parts: list[str] = []
        for key in ("execution_instruction", "executor_instruction", "content", "instruction", "request"):
            value = step.get(key) if isinstance(step, dict) else None
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
        prompt_contract = step.get("prompt_contract") if isinstance(step.get("prompt_contract"), dict) else {}
        for key in ("executor_instruction", "objective", "request"):
            value = prompt_contract.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
        flow = step.get("agent_execution_flow") if isinstance(step.get("agent_execution_flow"), list) else []
        for item in flow:
            if not isinstance(item, dict):
                continue
            if str(item.get("phase_role") or "") == "executor_llm_generation":
                purpose = item.get("purpose")
                if isinstance(purpose, str) and purpose.strip():
                    parts.append(purpose.strip())
        objective = step.get("objective")
        if isinstance(objective, str) and objective.strip():
            parts.append(objective.strip())
        seen: set[str] = set()
        unique: list[str] = []
        for part in parts:
            compact = " ".join(part.split())
            if compact and compact not in seen:
                seen.add(compact)
                unique.append(compact)
        return "\n".join(unique) or "Generate the requested final content."

    def _runtime_generation_public_brief(self, known: dict[str, Any]) -> dict[str, Any]:
        """Return the confirmed user-facing brief for model generation.

        The executor receives mixed runtime data: user-provided parameters,
        participant identifiers, planner metadata, and execution bookkeeping.
        Only user-facing scalar/list/dict values should drive the generation
        prompt.  This filter is structural and generic; it does not rely on any
        domain, agent name, or example phrase.
        """
        if not isinstance(known, dict):
            return {}
        excluded_exact = {
            "participant_name",
            "participant_id",
            "agent_name",
            "agent_id",
            "objective",
            "capability",
            "intent",
            "task_name",
            "community_id",
            "run_id",
            "node_id",
            "step_id",
            "timestamp",
            "system_clock",
            "timezone",
            "t",
        }
        excluded_fragments = (
            "participant_",
            "_id",
            "trace",
            "runtime",
            "planner",
            "execution_decision",
            "prompt_contract",
            "source_step",
        )
        public: dict[str, Any] = {}
        for raw_key, value in known.items():
            key = str(raw_key or "").strip()
            if not key:
                continue
            low = key.casefold()
            if low in excluded_exact:
                continue
            if any(fragment in low for fragment in excluded_fragments):
                continue
            if value in (None, "", [], {}):
                continue
            if isinstance(value, (str, int, float, bool, list, dict)):
                public[key] = value
        return public

    def _render_generation_brief_payload(self, public_brief: dict[str, Any]) -> str:
        lines: list[str] = []
        for key in sorted(public_brief):
            value = public_brief[key]
            if isinstance(value, list) and len(value) == 1:
                value = value[0]
            if isinstance(value, (dict, list)):
                rendered = json.dumps(make_json_safe(value), ensure_ascii=False, separators=(",", ":"))
            else:
                rendered = str(value)
            lines.append(f"- {key}: {rendered}")
        return "\n".join(lines)

    async def _try_model_generation_execution(
        self,
        *,
        run_id: str,
        node_id: str,
        step_id: str,
        capability: str,
        step: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Generate original output with the configured model.

        This is a generic execution path for tasks whose workflow contract asks
        for model-generated content rather than external evidence. It is not tied
        to any domain; the workflow/model chooses this method through
        execution_strategy or execution_method_policy.
        """
        tool_input = self._build_tool_input(
            step=step,
            run_id=run_id,
            node_id=node_id,
            step_id=step_id,
            user_input=state.get("input", ""),
        )
        known = {}
        if isinstance(tool_input.get("known"), dict):
            known.update(tool_input.get("known") or {})
        params = tool_input.get("parameters") if isinstance(tool_input.get("parameters"), dict) else {}
        if isinstance(params.get("known"), dict):
            known.update(params.get("known") or {})
        for key, value in params.items():
            if key in {"known", "optional", "missing_required", "missing_information", "context", "source_step"}:
                continue
            if key in {"timestamp", "system_clock", "timezone"} and key not in tool_input:
                continue
            if isinstance(value, (str, int, float, bool, list, dict)):
                known.setdefault(str(key), value)
        for key, value in tool_input.items():
            if key in {"known", "parameters", "optional", "context", "source_step"}:
                continue
            if isinstance(value, (str, int, float, bool, list, dict)):
                known.setdefault(str(key), value)

        schema = {
            "type": "object",
            "required": ["status", "answer_material"],
            "properties": {
                "status": {"type": "string"},
                "answer_material": {"type": "string"},
                "normalized_facts": {"type": "array"},
            },
            "additionalProperties": True,
        }
        prompt = {
            "system": (
                "Return JSON only. Produce the final deliverable itself from the "
                "executor instruction, objective, and confirmed parameters. Do not "
                "summarize the request, do not describe what the agent can do, do not "
                "return a plan, and do not echo parameters as the answer. Do not browse "
                "the web, cite external sources, invent provenance, or return code unless "
                "code itself is explicitly the requested final deliverable."
            )
        }
        executor_instruction = self._executor_generation_instruction(step=step)
        public_brief = self._runtime_generation_public_brief(known)
        parameter_lines = self._render_generation_brief_payload(public_brief)
        rendered = (
            "EXECUTION_ROLE=You are the final content executor, not a planner.\n"
            "DELIVERABLE_INSTRUCTION=" + executor_instruction[:900] +
            "\nCONFIRMED_USER_BRIEF_JSON=" + json.dumps(make_json_safe(public_brief), ensure_ascii=False, separators=(",", ":"))[:1800] +
            "\nCONFIRMED_USER_BRIEF=\n" + parameter_lines[:1800] +
            "\nEXECUTION_DIRECTIVE=Use CONFIRMED_USER_BRIEF as the concrete brief. Produce the completed final deliverable now in answer_material. The answer_material must contain only the deliverable content. Do not describe the task, agent, request, parameters, readiness, plan, or execution state."
        )
        try:
            generated = await self.provider_router.generate_json(
                run_id=run_id,
                node_id="content_generation_execution",
                adapter={
                    "adapter_id": "content_generation_execution_adapter",
                    "provider_route": ["ollama", "openai"],
                    "provider_timeout_seconds": 90,
                    "max_provider_attempts": 1,
                    "max_prompt_tokens": 900,
                    "max_schema_chars": 600,
                    "provider_options": {"temperature": 0.4, "num_predict": 900, "num_ctx": 2048, "think": False},
                },
                prompt=prompt,
                rendered_user_prompt=rendered,
                schema=schema,
            )
        except Exception as exc:
            return {
                "input": tool_input,
                "result": {
                    "status": "error",
                    "error": {"code": "content_generation_failed", "message": str(exc)},
                    "data": {},
                    "source": "model_runtime",
                    "requires_human_confirmation": False,
                },
            }

        answer = str(generated.get("answer_material") or generated.get("final_answer") or generated.get("content") or "").strip()
        if not answer:
            return None
        quality = self._generated_answer_quality(answer=answer, step=step, known=known)

        # A local model may return a planning/request summary even when the
        # content-generation path asked for the final deliverable.  Retry once
        # with a narrower prompt before failing the node.  This is generic: it
        # relies only on the output contract and quality decision, not on any
        # domain-specific task names or example requests.
        if not quality.get("passed"):
            retry_rendered = (
                rendered
                + "\nPREVIOUS_OUTPUT_REJECTED_REASON="
                + str(quality.get("reason") or "quality gate failed")
                + "\nReturn the completed final deliverable itself in answer_material. "
                  "Do not describe the assignment, capability, plan, readiness, or parameters."
            )
            try:
                repaired = await self.provider_router.generate_json(
                    run_id=run_id,
                    node_id="content_generation_execution_retry",
                    adapter={
                        "adapter_id": "content_generation_execution_retry_adapter",
                        "provider_route": ["ollama", "openai"],
                        "provider_timeout_seconds": 90,
                        "max_provider_attempts": 1,
                        "max_prompt_tokens": 900,
                        "max_schema_chars": 600,
                        "provider_options": {"temperature": 0.35, "num_predict": 1200, "num_ctx": 2048, "think": False},
                    },
                    prompt=prompt,
                    rendered_user_prompt=retry_rendered,
                    schema=schema,
                )
                repaired_answer = str(repaired.get("answer_material") or repaired.get("final_answer") or repaired.get("content") or "").strip()
                repaired_quality = self._generated_answer_quality(answer=repaired_answer, step=step, known=known) if repaired_answer else {"passed": False, "reason": "empty_answer_material", "source_type": "model_generated"}
                if repaired_quality.get("passed"):
                    generated = repaired
                    answer = repaired_answer
                    quality = repaired_quality
            except Exception:
                pass

        if not quality.get("passed"):
            return {
                "input": tool_input,
                "result": {
                    "status": "failed_quality_gate",
                    "error": {"code": "generated_answer_quality_failed", "message": str(quality.get("reason") or "quality gate failed")},
                    "data": {"answer_material_quality": quality, "rejected_answer_preview": answer[:300]},
                    "source": "model_generated_content",
                    "requires_human_confirmation": False,
                },
            }
        result = {
            "status": "success",
            "data": {
                "answer_material": answer,
                "normalized_facts": generated.get("normalized_facts") if isinstance(generated.get("normalized_facts"), list) else [],
                "answer_material_quality": quality,
            },
            "source": "model_generated_content",
            "requires_human_confirmation": False,
            "provenance": {
                "source": "model_runtime",
                "execution_claims": {
                    "real_execution_declared": True,
                    "no_mock_data_declared": True,
                    "network_declared": False,
                    "live_verification_passed": False,
                    "evidence_quality_passed": True,
                },
            },
        }
        return {"input": tool_input, "result": result}

    def _generated_answer_quality(self, *, answer: str, step: dict[str, Any], known: dict[str, Any]) -> dict[str, Any]:
        """Generic guard against returning planning/request summaries as final content.

        The guard is intentionally domain-neutral. It only checks whether the
        candidate answer is the actual deliverable promised by the execution
        contract, rather than a meta-description of the task, capability, or
        parameters.  It does not hard-code task names or business vocabulary.
        """
        text = " ".join(str(answer or "").split())
        lower = text.casefold()
        words = text.split()
        if not text:
            return {"passed": False, "reason": "empty_answer_material", "source_type": "model_generated"}

        # Generic meta-output markers. These indicate that the model described
        # the assignment or execution state instead of producing the deliverable.
        hard_summary_markers = (
            "has been tasked with",
            "was tasked with",
            "is tasked with",
            "tasked with",
            "has been asked to",
            "was asked to",
            "asked to",
            "has been requested to",
            "is requested to",
            "ready to",
            "is ready to",
            "will write",
            "will produce",
            "will generate",
            "will create",
            "going to write",
            "going to produce",
            "is capable of",
            "can produce",
            "can generate",
            "the agent will",
            "the task is to",
        )
        if any(marker in lower for marker in hard_summary_markers):
            return {
                "passed": False,
                "reason": "answer_looks_like_request_or_capability_summary",
                "source_type": "model_generated",
                "actual_words": len(words),
            }

        soft_summary_markers = (
            "capable of",
            "requirements",
            "parameters",
            "based on the provided",
            "next step",
            "objective is",
            "request is",
        )
        if len(words) < 80 and any(marker in lower for marker in soft_summary_markers):
            return {
                "passed": False,
                "reason": "answer_looks_like_short_internal_summary",
                "source_type": "model_generated",
                "actual_words": len(words),
            }

        requested_counts: list[int] = []
        import re

        def collect_numbers(value: Any) -> None:
            if value is None:
                return
            if isinstance(value, dict):
                for nested in value.values():
                    collect_numbers(nested)
                return
            if isinstance(value, (list, tuple, set)):
                for nested in value:
                    collect_numbers(nested)
                return
            for match in re.findall(r"(?<!\d)(\d{2,5})(?!\d)", str(value)):
                try:
                    requested_counts.append(int(match))
                except ValueError:
                    pass

        collect_numbers(known)
        # Include the step contract itself because some generated workflows keep
        # size/format requirements in objective/notes instead of parameters.
        collect_numbers({
            "name": step.get("name"),
            "objective": step.get("objective"),
            "description": step.get("description"),
            "notes": step.get("notes"),
            "input_schema": step.get("input_schema"),
            "output_schema": step.get("output_schema"),
            "validation_rule": step.get("validation_rule"),
        })

        if requested_counts:
            target = max(requested_counts)
            if target >= 50 and len(words) < max(30, int(target * 0.4)):
                return {
                    "passed": False,
                    "reason": "answer_too_short_for_requested_size",
                    "source_type": "model_generated",
                    "requested_size_hint": target,
                    "actual_words": len(words),
                }
        return {"passed": True, "reason": "model_generated_content_contract", "source_type": "model_generated"}


    def _render_confirmed_parameters_for_generation(self, known: dict[str, Any]) -> str:
        """Render confirmed runtime parameters as generic executor constraints."""
        if not isinstance(known, dict) or not known:
            return "- no confirmed parameter values were provided"
        lines: list[str] = []
        for key in sorted(known.keys(), key=lambda item: str(item)):
            value = known.get(key)
            if value is None or value == "":
                continue
            if isinstance(value, (dict, list)):
                rendered = json.dumps(make_json_safe(value), ensure_ascii=False, separators=(",", ":"))
            else:
                rendered = str(value)
            lines.append(f"- {key}: {rendered[:400]}")
        return "\n".join(lines) if lines else "- no confirmed parameter values were provided"

    async def _try_local_knowledge_execution(
        self,
        *,
        run_id: str,
        node_id: str,
        step_id: str,
        capability: str,
        step: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any] | None:
        tool_input = self._build_tool_input(
            step=step, run_id=run_id, node_id=node_id, step_id=step_id, user_input=state.get("input", "")
        )
        required_terms = self._required_terms_from_tool_input(tool_input)
        query = " ".join([str(state.get("input") or ""), str(step.get("objective") or ""), capability])
        await event_bus.emit(run_id, {
            "type": "LOCAL_KNOWLEDGE_FIRST_CHECK",
            "title": "Local knowledge first check",
            "message": "Checking local runtime knowledge before web/API/tool generation.",
            "node_id": node_id,
            "step_id": step_id,
            "result": {"required_terms": required_terms},
        })
        hint_item = self.knowledge.best_hint(query, required_terms=required_terms)
        if hint_item:
            await event_bus.emit(run_id, {
                "type": "LOCAL_KNOWLEDGE_HINT_SELECTED",
                "title": "Local knowledge hint selected",
                "message": "A matching local memory was found, but it is hint-only and will not be used as final answer evidence.",
                "node_id": node_id,
                "step_id": step_id,
                "result": {
                    "source": hint_item.get("source"),
                    "classification": hint_item.get("classification"),
                    "coverage": hint_item.get("coverage"),
                },
            })

        item = self.knowledge.best_covered(query, required_terms=required_terms, min_score=1.0, final_answer_only=True)
        rag_payload = None
        if not item:
            rag_payload = await self.knowledge.rag_answer(query, limit=5, synthesize=True)
            if not isinstance(rag_payload, dict) or rag_payload.get("status") != "evidence_found":
                await event_bus.emit(run_id, {
                    "type": "LOCAL_KNOWLEDGE_NO_FINAL_EVIDENCE",
                    "title": "No final-answer local knowledge",
                    "message": "Local knowledge did not contain eligible final-answer evidence; continuing to web/API/tool execution.",
                    "node_id": node_id,
                    "step_id": step_id,
                    "result": {"hint_available": bool(hint_item)},
                })
                return None
        answer_material = str((rag_payload or {}).get("answer") or (rag_payload or {}).get("answer_material") or (item.get("text_excerpt") if item else "")).strip()
        result = {
            "status": "success",
            "data": {
                "answer_material": answer_material,
                "source": item.get("source") if item else "runtime_document_knowledge",
                "coverage": item.get("coverage") if item else {},
                "citations": (rag_payload or {}).get("citations") or [],
                "known_parameters": tool_input.get("known") or (tool_input.get("parameters") or {}).get("known") or {},
                "local_knowledge_used": True,
                "local_knowledge_classification": item.get("classification") if item else {"memory_type": "user_provided_document_fact", "usage_scope": "final_answer_evidence"},
                "answer_material_quality": {
                    "passed": True,
                    "reason": "eligible_final_answer_local_knowledge",
                    "source": item.get("source") if item else "runtime_document_knowledge",
                },
            },
            "source": "runtime_local_knowledge",
            "requires_human_confirmation": False,
            "provenance": {
                "source": "runtime_knowledge",
                "execution_claims": {
                    "real_execution_declared": True,
                    "no_mock_data_declared": True,
                    "network_declared": False,
                    "live_verification_passed": False,
                    "evidence_quality_passed": True,
                },
            },
        }
        await event_bus.emit(run_id, {
            "type": "LOCAL_KNOWLEDGE_SELECTED",
            "title": "Local knowledge selected",
            "message": "Local knowledge covered the runtime parameters; web/API/codegen skipped.",
            "node_id": node_id,
            "step_id": step_id,
            "result": {"coverage": item.get("coverage"), "source": item.get("source")},
        })
        return {"input": tool_input, "result": result}

    def _required_terms_from_tool_input(self, tool_input: dict[str, Any]) -> dict[str, list[str]]:
        known: dict[str, Any] = {}
        if isinstance(tool_input.get("known"), dict):
            known.update(tool_input.get("known") or {})
        params = tool_input.get("parameters") if isinstance(tool_input.get("parameters"), dict) else {}
        if isinstance(params.get("known"), dict):
            known.update(params.get("known") or {})
        for key, value in list(tool_input.items()):
            if key in {"known", "parameters", "optional", "context", "source_step"}:
                continue
            if isinstance(value, (str, int, float, bool)) and value not in {"", None}:
                known.setdefault(str(key), value)
        ignored = {"detail_level", "semantic_modifiers", "language", "locale", "unit", "units"}
        required: dict[str, list[str]] = {}
        for key, value in known.items():
            if key in ignored:
                continue
            aliases = self._value_aliases(value)
            if aliases:
                required[str(key)] = aliases
        return required

    def _value_aliases(self, value: Any) -> list[str]:
        raw = str(value).strip()
        if not raw:
            return []
        aliases = [raw]
        if len(raw) >= 10 and raw[4:5] == "-" and raw[7:8] == "-":
            y, m, d = raw[:4], raw[5:7], raw[8:10]
            try:
                mi, di = int(m), int(d)
                aliases.extend(DateAliasGenerator().aliases_for(raw))
            except Exception:
                pass
        if "," in raw:
            aliases.extend([part.strip() for part in raw.split(",") if part.strip()])
        return list(dict.fromkeys(aliases))


    async def _execute_registered_module(
        self,
        *,
        run_id: str,
        node_id: str,
        step_id: str,
        capability: str,
        step: dict[str, Any],
        state: dict[str, Any],
        component_type: str = "runtime_module",
    ) -> dict[str, Any] | None:
        """Load and execute an already-registered runtime module by capability.

        This is the v50 continuation bridge. When a previous run or an earlier
        phase generated/registered a module, execution must not stop at a
        generated-capability review. It should reuse the registered module and
        continue the workflow. The method is domain-neutral: it only uses
        capability metadata and the module registry.
        """
        module = self.module_loader.load_by_capability(capability)
        if module is None:
            await event_bus.emit(run_id, {
                "type": "MODULE_REUSE_UNAVAILABLE",
                "title": "Registered module unavailable",
                "message": f"A module is registered for capability={capability}, but it could not be loaded.",
                "node_id": node_id,
                "step_id": step_id,
            })
            return None

        module_record = self.module_loader.registry.find_by_capability(capability) or {"module_id": capability}
        module_input = self._build_tool_input(
            step=step,
            run_id=run_id,
            node_id=node_id,
            step_id=step_id,
            user_input=state.get("input", ""),
        )
        await event_bus.emit(run_id, {
            "type": "MODULE_REUSE_EXECUTION_STARTED",
            "title": "Reusable module execution started",
            "message": f"Executing registered runtime module for capability={capability}",
            "node_id": node_id,
            "step_id": step_id,
            "result": {"module": module_record, "input": module_input},
        })
        trace = self.provenance.start(
            run_id=run_id,
            node_id=node_id,
            step_id=step_id,
            component_type=component_type,
            component_id=str(module_record.get("module_id") or capability),
            capability=capability,
            input_data=module_input,
            artifact=module_record,
        )
        try:
            raw_result = module.run(module_input)
            result = self._normalize_runtime_execution_result(raw_result, source=component_type)
            result = self.generated_result_verifier.enforce(result, artifact=module_record)
            trace = self.provenance.finish(
                trace,
                output=result,
                status="success" if self._is_success_result(result) else "error",
                error=result.get("error") if isinstance(result, dict) else None,
            )
            result = self.provenance.attach(result, trace)
        except Exception as exc:
            result = {"status": "error", "error": {"message": str(exc)}, "data": {}, "source": component_type}
            trace = self.provenance.finish(trace, output=result, status="error", error=result.get("error"))
            result = self.provenance.attach(result, trace)

        await event_bus.emit(run_id, {
            "type": "MODULE_REUSE_EXECUTED",
            "title": "Reusable module executed",
            "message": f"Registered module executed for capability={capability}",
            "node_id": node_id,
            "step_id": step_id,
            "result": result,
        })
        if isinstance(result, dict) and result.get("provenance"):
            await event_bus.emit(run_id, {
                "type": "EXECUTION_PROVENANCE_RECORDED",
                "title": "Execution provenance recorded",
                "message": f"Recorded provenance for step={step_id}",
                "node_id": node_id,
                "step_id": step_id,
                "result": result.get("provenance"),
            })
        return {"module": module, "registry_record": module_record, "input": module_input, "result": result}



    def _normalize_runtime_execution_result(self, value: Any, *, source: str) -> dict[str, Any]:
        """Normalize runtime tool/module outputs into a generic success/error contract.

        Runtime-generated modules are allowed to return a plain data object, for
        example {"value": 25, "label": "ok"}. A missing `status`
        field must not be treated as failure. This method stays domain-neutral:
        it only checks generic error/status shape and wraps useful payloads into
        the common result contract.
        """
        if isinstance(value, dict):
            raw_status = str(value.get("status", "")).lower().strip()
            has_error = bool(value.get("error"))

            if raw_status in {"success", "ok", "executed"} and not has_error:
                normalized = dict(value)
                normalized["status"] = "success"
                normalized.setdefault("source", source)
                if "data" not in normalized:
                    data = {k: v for k, v in value.items() if k not in {"status", "source", "requires_human_confirmation"}}
                    normalized["data"] = data
                return normalized

            if raw_status in {"error", "failed", "failure"} or has_error:
                error = value.get("error") if isinstance(value.get("error"), dict) else {"message": str(value.get("error") or value)}
                return {
                    "status": "error",
                    "error": error,
                    "data": value.get("data") if isinstance(value.get("data"), dict) else {},
                    "source": value.get("source") or source,
                    "requires_human_confirmation": bool(value.get("requires_human_confirmation", False)),
                }

            # Plain dict payload without a status is a valid successful result.
            return {
                "status": "success",
                "data": value,
                "source": source,
                "requires_human_confirmation": bool(value.get("requires_human_confirmation", False)),
            }

        if value is None:
            return {
                "status": "error",
                "error": {"message": "Runtime component returned no result."},
                "data": {},
                "source": source,
                "requires_human_confirmation": False,
            }

        return {
            "status": "success",
            "data": {"value": value},
            "source": source,
            "requires_human_confirmation": False,
        }

    def _is_success_result(self, result: Any) -> bool:
        return isinstance(result, dict) and result.get("status") == "success"

    def _result_error_message(self, result: Any, fallback: str) -> str:
        if isinstance(result, dict):
            error = result.get("error")
            if isinstance(error, dict):
                message = error.get("message")
                if isinstance(message, str) and message.strip():
                    return message.strip()
            if isinstance(result.get("message"), str) and result.get("message").strip():
                return result.get("message").strip()
        return fallback



    def _build_tool_input(
        self,
        *,
        step: dict[str, Any],
        run_id: str,
        node_id: str,
        step_id: str,
        user_input: str,
    ) -> dict[str, Any]:
        """Build a generic, schema-friendly tool input object.

        Runtime-generated tools may declare schemas that require fields at the
        top level, while workflow planning usually stores values under
        parameters.known / parameters.optional. To keep ai_core domain-neutral,
        this method does not infer meanings from field names. It simply exposes
        the already-structured runtime metadata in both canonical nested form
        and flattened top-level form so reusable generated tools can validate
        reliably.
        """
        params = step.get("parameters") if isinstance(step.get("parameters"), dict) else {}
        known = params.get("known") if isinstance(params.get("known"), dict) else {}
        optional = params.get("optional") if isinstance(params.get("optional"), dict) else {}
        if not known and not optional:
            # Runtime-generated routes may store confirmed values as a flat
            # parameters object instead of parameters.known. Preserve those
            # existing values as known execution inputs without interpreting
            # field names or adding any task-specific assumptions.
            known = {
                str(key): value
                for key, value in params.items()
                if key not in {"known", "optional", "missing_required", "missing_information"}
                and isinstance(value, (str, int, float, bool, list, dict))
            }

        tool_input: dict[str, Any] = {}
        for source in (known, optional):
            for key, value in source.items():
                if key not in tool_input:
                    tool_input[str(key)] = value

        # Keep both the raw planner structure and a flattened schema-friendly
        # parameters object. Runtime-generated tools often declare required
        # fields under $.parameters.<field>, while planners place values under
        # parameters.known / parameters.optional. This generic merge does not
        # infer field meanings; it only preserves already-known values in the
        # location most JSON schemas commonly validate.
        merged_parameters: dict[str, Any] = {}
        for source in (known, optional):
            for key, value in source.items():
                merged_parameters[str(key)] = value
        for key, value in params.items():
            if key not in {"known", "optional"} and key not in merged_parameters:
                merged_parameters[str(key)] = value
        now_utc = datetime.now(timezone.utc).isoformat()
        merged_parameters.setdefault("timestamp", now_utc)
        merged_parameters.setdefault("system_clock", now_utc)
        merged_parameters.setdefault("timezone", "UTC")

        tool_input.update({
            "parameters": merged_parameters,
            "raw_parameters": params,
            "known": known,
            "optional": optional,
            "context": {
                "run_id": run_id,
                "node_id": node_id,
                "step_id": step_id,
                "user_input": user_input,
            },
            "source_step": step,
        })
        return tool_input


    def _execution_strategy(self, step: dict[str, Any], normalized_plan: dict[str, Any] | None = None) -> list[str]:
        """Return a normalized, domain-neutral execution strategy.

        The strategy controls the order of generic runtime approaches.  It does
        not name a concrete provider, API, model, website, business domain, or
        generated implementation.
        """
        raw = None
        if isinstance(step, dict):
            raw = step.get("execution_strategy") or step.get("strategy")
        if raw is None and isinstance(normalized_plan, dict):
            raw = normalized_plan.get("execution_strategy")
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list):
            raw = ["local_knowledge", "web_evidence", "tool_generation"]
        allowed = {"local_knowledge", "web_evidence", "tool_generation", "registered_component", "human_interaction", "runtime_native", "structured_provider"}
        output: list[str] = []
        for item in raw:
            value = str(item or "").strip().lower().replace("-", "_")
            if value in allowed and value not in output:
                output.append(value)
        if not output:
            output = ["local_knowledge", "web_evidence", "tool_generation"]
        return output

    def _strategy_prefers(self, strategy: list[str], first: str, *, before: str) -> bool:
        try:
            first_index = strategy.index(first)
        except ValueError:
            return False
        try:
            before_index = strategy.index(before)
        except ValueError:
            return True
        return first_index < before_index

    async def _try_strategy_web_evidence_execution(
        self,
        *,
        run_id: str,
        node_id: str,
        step_id: str,
        capability: str,
        step: dict[str, Any],
        state: dict[str, Any],
        reason: str,
    ) -> dict[str, Any] | None:
        """Execute the generic web-evidence branch before generated components.

        This method is intentionally domain-neutral.  It fetches candidate pages,
        extracts text/DOM/attribute evidence through the generic research tool,
        materializes structured evidence, and returns a result suitable for final
        synthesis.  It never returns raw markup as the user-facing answer.
        """
        await event_bus.emit(run_id, {
            "type": "EXECUTION_STRATEGY_WEB_EVIDENCE_STARTED",
            "title": "Web evidence strategy started",
            "message": "Trying generic evidence retrieval before generated component execution.",
            "node_id": node_id,
            "step_id": step_id,
            "result": {"reason": reason, "strategy": self._execution_strategy(step, {})},
        })
        try:
            cost_snapshot = self.runtime_cost_policy.snapshot(state)
            # v2.9.38: API-first adaptive execution.  Browser/page scraping is
            # intentionally demoted to the last fallback because page structure is
            # unstable.  The runtime first asks the configured intelligence route
            # to discover free/no-key structured APIs. If those do not produce a
            # verified executable result, credential-protected API candidates may
            # be surfaced by the normal credential interaction path. Only after
            # the API path fails or is skipped does the runtime investigate web
            # pages as evidence.
            api_discovery = {}
            direct_execution = None

            # Execute configured/free structured providers before model-based API
            # discovery. This avoids heavy tool-selection/fact-verification LLM
            # loops when a trusted structured provider is already configured and
            # the step contains enough normalized parameters.
            structured_execution = await asyncio.wait_for(self.structured_provider_executor.execute(
                run_id=run_id,
                node_id=node_id,
                step_id=step_id,
                capability=capability,
                step=step,
                state=state,
                advisory={},
            ), timeout=cost_snapshot.stage_timeout("api_call", 45))
            if structured_execution and structured_execution.get("status") == "success":
                direct_execution = structured_execution
                await event_bus.emit(run_id, {
                    "type": "STRUCTURED_PROVIDER_SUFFICIENT_BEFORE_DISCOVERY",
                    "title": "Structured provider sufficient before discovery",
                    "message": "A configured structured provider produced verified material; model discovery and web fallback were skipped.",
                    "node_id": node_id,
                    "step_id": step_id,
                    "result": self._compact_direct_result_for_event(structured_execution.get("result") or {}),
                })

            if not direct_execution:
                try:
                    api_discovery = await asyncio.wait_for(self.api_discovery.discover(
                        run_id=run_id,
                        node_id=node_id,
                        capability=capability,
                        step=step,
                        user_input=state.get("input", ""),
                    ), timeout=cost_snapshot.stage_timeout("api_discovery", 30))
                except Exception as api_exc:
                    await event_bus.emit(run_id, {
                        "type": "API_FIRST_DISCOVERY_FAILED",
                        "title": "API-first discovery failed",
                        "message": str(api_exc),
                        "node_id": node_id,
                        "step_id": step_id,
                    })

            if not direct_execution and api_discovery:
                await event_bus.emit(run_id, {
                    "type": "API_FIRST_DISCOVERY_DONE",
                    "title": "API-first discovery completed",
                    "message": "Structured API candidates were collected before web-page fallback.",
                    "node_id": node_id,
                    "step_id": step_id,
                    "result": self._compact_api_discovery_for_event(api_discovery),
                })
                direct_execution = await asyncio.wait_for(self._try_direct_evidence_execution_from_discovery(
                    run_id=run_id,
                    node_id=node_id,
                    step_id=step_id,
                    capability=capability,
                    step=step,
                    state=state,
                    api_discovery=api_discovery,
                    external_discovery={},
                    reason=reason + "_api_first",
                ), timeout=cost_snapshot.stage_timeout("api_call", 45))
                if direct_execution and direct_execution.get("status") == "success":
                    await event_bus.emit(run_id, {
                        "type": "API_FIRST_EVIDENCE_SUFFICIENT",
                        "title": "API-first evidence sufficient",
                        "message": "Structured API evidence satisfied the execution contract; web-page fallback was skipped.",
                        "node_id": node_id,
                        "step_id": step_id,
                        "result": self._compact_direct_result_for_event(direct_execution.get("result") or {}),
                    })
                elif direct_execution and direct_execution.get("status") == "partial":
                    await event_bus.emit(run_id, {
                        "type": "API_FIRST_EVIDENCE_PARTIAL",
                        "title": "API-first evidence partial",
                        "message": "Structured API evidence was investigated but did not satisfy the execution contract.",
                        "node_id": node_id,
                        "step_id": step_id,
                        "result": self._compact_direct_result_for_event(direct_execution.get("result") or {}),
                    })

            if not direct_execution or direct_execution.get("status") != "success":
                external_discovery = await asyncio.wait_for(self.external_discovery.discover(
                    run_id=run_id,
                    node_id=node_id,
                    capability=capability,
                    step=step,
                    user_input=state.get("input", ""),
                ), timeout=cost_snapshot.stage_timeout("web_discovery", 30))
                web_execution = await asyncio.wait_for(self._try_direct_evidence_execution_from_discovery(
                    run_id=run_id,
                    node_id=node_id,
                    step_id=step_id,
                    capability=capability,
                    step=step,
                    state=state,
                    api_discovery={},
                    external_discovery=external_discovery,
                    reason=reason + "_web_fallback_after_api",
                ), timeout=cost_snapshot.stage_timeout("web_search", 90))
                if web_execution:
                    web_result = web_execution.get("result") if isinstance(web_execution.get("result"), dict) else {}
                    web_result.setdefault("api_first_attempt", self._compact_api_discovery_for_event(api_discovery) if api_discovery else {})
                    direct_execution = web_execution
            if direct_execution and direct_execution.get("status") in {"success", "partial"}:
                tool_input = self._build_tool_input(
                    step=step,
                    run_id=run_id,
                    node_id=node_id,
                    step_id=step_id,
                    user_input=state.get("input", ""),
                )
                selected_status = str(direct_execution.get("status") or "success")
                await event_bus.emit(run_id, {
                    "type": "EXECUTION_STRATEGY_WEB_EVIDENCE_SELECTED" if selected_status == "success" else "EXECUTION_STRATEGY_WEB_EVIDENCE_PARTIAL_SELECTED",
                    "title": "Web evidence strategy selected" if selected_status == "success" else "Web evidence investigation report selected",
                    "message": "Generic evidence was sufficient; generated component execution was skipped." if selected_status == "success" else "Generic evidence was investigated but did not create verified result material; returning the investigation report instead of falling through to unrelated sources.",
                    "node_id": node_id,
                    "step_id": step_id,
                    "result": self._compact_direct_result_for_event(direct_execution.get("result") or {}),
                })
                return {
                    "tool": direct_execution.get("tool") or {"id": "browser_network_deepsearch", "source": "browser_or_web_structured_evidence"},
                    "input": tool_input,
                    "result": direct_execution.get("result"),
                }
        except Exception as exc:
            await event_bus.emit(run_id, {
                "type": "EXECUTION_STRATEGY_WEB_EVIDENCE_FAILED",
                "title": "Web evidence strategy failed",
                "message": str(exc),
                "node_id": node_id,
                "step_id": step_id,
            })
        return None

    async def _try_generate_executable_module(
        self,
        *,
        run_id: str,
        node_id: str,
        step_id: str,
        capability: str,
        step: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any] | None:
        api_discovery = await self.api_discovery.discover(
            run_id=run_id,
            node_id=node_id,
            capability=capability,
            step=step,
            user_input=state.get("input", ""),
        )
        generation_request = {
            "request_type": "runtime_module_artifact_generation",
            "capability": capability,
            "step": step,
            "user_input": state.get("input", ""),
            "api_discovery": api_discovery,
            "constraints": {
                "must_be_reusable": True,
                "must_define_runtime_interface": ["validate_config", "health_check", "run"],
                "must_return_schema_compatible_output": True,
                "must_not_log_secrets": True,
                "must_not_perform_irreversible_actions_without_confirmation": True,
                "no_mock_data": True,
                "must_use_real_network_when_external_data_is_required": True,
                "must_include_request_response_evidence": True,
                "must_declare_execution_claims": True,
                "must_include_live_verification_metadata": True,
            },
            "expected_contract": {
                "module_id": "string",
                "manifest": "module.json compatible object with execution_claims, api_discovery, verification",
                "files": {"module.py": "python source code"},
            },
        }
        await event_bus.emit(run_id, {
            "type": "MODULE_GENERATION_STARTED",
            "title": "Runtime module generation started",
            "message": f"Generating reusable module artifact for capability={capability}",
            "node_id": node_id,
            "step_id": step_id,
            "result": generation_request,
        })
        try:
            artifact = await self.module_artifact_generator.generate_artifact(
                run_id=run_id, node_id=node_id, generation_request=generation_request
            )
            installed = self.module_installer.install_artifact(
                artifact=artifact, capability=capability, source_step=step, user_input=state.get("input", "")
            )
            await event_bus.emit(run_id, {
                "type": "MODULE_REGISTERED",
                "title": "Runtime module registered",
                "message": f"Reusable runtime module registered for capability={capability}",
                "node_id": node_id,
                "step_id": step_id,
                "result": installed,
            })
            module = self.module_loader.load_by_capability(capability)
            if module is None:
                raise RuntimeError("Generated module was registered but could not be loaded.")
            module_input = self._build_tool_input(
                step=step, run_id=run_id, node_id=node_id, step_id=step_id, user_input=state.get("input", "")
            )
            await event_bus.emit(run_id, {
                "type": "MODULE_EXECUTION_STARTED",
                "title": "Runtime module execution started",
                "message": f"Executing generated module for capability={capability}",
                "node_id": node_id,
                "step_id": step_id,
            })
            trace = self.provenance.start(
                run_id=run_id,
                node_id=node_id,
                step_id=step_id,
                component_type="runtime_generated_module",
                component_id=str(installed.get("module_id") or capability),
                capability=capability,
                input_data=module_input,
                artifact=installed,
            )
            raw_result = module.run(module_input)
            result = self._normalize_runtime_execution_result(raw_result, source="runtime_generated_module")
            result = self.generated_result_verifier.enforce(result, artifact=installed)
            trace = self.provenance.finish(
                trace,
                output=result,
                status="success" if self._is_success_result(result) else "error",
                error=result.get("error") if isinstance(result, dict) else None,
            )
            result = self.provenance.attach(result, trace)
            await event_bus.emit(run_id, {
                "type": "MODULE_EXECUTED",
                "title": "Runtime module executed",
                "message": f"Generated module executed for capability={capability}",
                "node_id": node_id,
                "step_id": step_id,
                "result": result,
            })
            if isinstance(result, dict) and result.get("provenance"):
                await event_bus.emit(run_id, {
                    "type": "EXECUTION_PROVENANCE_RECORDED",
                    "title": "Execution provenance recorded",
                    "message": f"Recorded provenance for step={step_id}",
                    "node_id": node_id,
                    "step_id": step_id,
                    "result": result.get("provenance"),
                })
            return {"module": module, "registry_record": installed, "result": result}
        except Exception as exc:
            await event_bus.emit(run_id, {
                "type": "MODULE_GENERATION_FAILED",
                "title": "Runtime module generation failed",
                "message": str(exc),
                "node_id": node_id,
                "step_id": step_id,
            })
            return None


    async def _try_generate_executable_tool(
        self,
        *,
        run_id: str,
        node_id: str,
        step_id: str,
        capability: str,
        step: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Ask the runtime intelligence layer to generate a reusable tool artifact.

        This is generic: ai_core does not choose an API, endpoint, provider, or
        business strategy. The LLM/runtime-generated artifact must declare its
        files, manifest, schemas, safety, retry/timeout behavior, and callable.
        """
        external_discovery = await self.external_discovery.discover(
            run_id=run_id,
            node_id=node_id,
            capability=capability,
            step=step,
            user_input=state.get("input", ""),
        )
        api_discovery = await self.api_discovery.discover(
            run_id=run_id,
            node_id=node_id,
            capability=capability,
            step=step,
            user_input=state.get("input", ""),
        )
        resolution_decision = self.capability_resolution.decide(
            has_registered_tool=False,
            has_registered_module=False,
            requires_external_data=True,
            api_discovery=api_discovery,
            external_discovery=external_discovery,
        )
        await event_bus.emit(run_id, {
            "type": "CAPABILITY_RESOLUTION_DECISION",
            "title": "Capability resolution decision",
            "message": f"resolution_type={resolution_decision.get('resolution_type')} strategy={resolution_decision.get('candidate_strategy')}",
            "node_id": node_id,
            "step_id": step_id,
            "result": resolution_decision,
        })

        direct_from_evidence = await self._try_direct_evidence_execution_from_discovery(
            run_id=run_id,
            node_id=node_id,
            step_id=step_id,
            capability=capability,
            step=step,
            state=state,
            api_discovery=api_discovery,
            external_discovery=external_discovery,
            reason="before_runtime_tool_generation",
        )
        if direct_from_evidence:
            return direct_from_evidence

        endpoint_verification = api_discovery.get("endpoint_verification") if isinstance(api_discovery, dict) else {}
        recommended_tool_type = str((endpoint_verification or {}).get("recommended_tool_type") or "").strip()
        verified_json_api = bool((endpoint_verification or {}).get("verified_json_api"))
        if recommended_tool_type in {"web_extract", "browser_extract", "browser_automation"} and not verified_json_api:
            tool_input = self._build_tool_input(
                step=step, run_id=run_id, node_id=node_id, step_id=step_id, user_input=state.get("input", "")
            )
            deterministic_web_tool = await self._build_and_verify_generic_web_extract_tool(
                run_id=run_id,
                node_id=node_id,
                step_id=step_id,
                capability=capability,
                step=step,
                state=state,
                api_discovery=api_discovery,
                external_discovery=external_discovery,
                candidate=None,
                tool_input=tool_input,
                reason="endpoint_recommended_web_extract_before_codegen",
            )
            if deterministic_web_tool:
                await event_bus.emit(run_id, {
                    "type": "WEB_EXTRACT_SELECTED_BEFORE_CODEGEN",
                    "title": "Web extraction selected before codegen",
                    "message": "Endpoint verification recommended web extraction; LLM code generation was skipped.",
                    "node_id": node_id,
                    "step_id": step_id,
                    "result": self._public_tool_spec(deterministic_web_tool),
                })
                return deterministic_web_tool

        if self.evidence_short_circuit.should_bypass_generated_execution(api_discovery, external_discovery):
            direct_from_short_circuit = await self._try_direct_evidence_execution_from_discovery(
                run_id=run_id,
                node_id=node_id,
                step_id=step_id,
                capability=capability,
                step=step,
                state=state,
                api_discovery=api_discovery,
                external_discovery=external_discovery,
                reason="evidence_satisfied_short_circuit_before_generated_artifact",
            )
            if direct_from_short_circuit:
                await event_bus.emit(run_id, {
                    "type": "EVIDENCE_SATISFIED_SHORT_CIRCUIT",
                    "title": "Evidence satisfied before generated artifact",
                    "message": "Generated artifact creation skipped because evidence already satisfied the request.",
                    "node_id": node_id,
                    "step_id": step_id,
                })
                return direct_from_short_circuit

        if api_discovery.get("status") != "success" and not external_discovery.get("documents") and not external_discovery.get("repositories"):
            await event_bus.emit(run_id, {
                "type": "RUNTIME_TOOL_GENERATION_BLOCKED",
                "title": "Runtime tool generation blocked",
                "message": "API documentation evidence was insufficient for safe executable tool generation.",
                "node_id": node_id,
                "step_id": step_id,
                "result": api_discovery,
            })
            return {
                "__runtime_blocked__": True,
                "status": "api_documentation_evidence_insufficient",
                "reason": "API documentation evidence was insufficient for safe executable tool generation.",
                "discovery": {"api_discovery": api_discovery, "external_solution_discovery": external_discovery},
            }

        generation_request = {
            "request_type": "runtime_tool_artifact_generation",
            "capability": capability,
            "step": step,
            "user_input": state.get("input", ""),
            "runtime_request_semantics": api_discovery.get("request", {}).get("runtime_request_semantics", {}),
            "api_discovery": api_discovery,
            "external_solution_discovery": external_discovery,
            "capability_resolution_decision": resolution_decision,
            "documentation_understanding": (api_discovery.get("result") or {}).get("documentation_understanding", {}),
            "multi_candidate_policy": {
                "must_not_stop_after_first_external_failure": True,
                "try_candidates_in_order": True,
                "record_each_attempt": True,
                "failure_categories_to_continue": [
                    "auth_or_blocked",
                    "timeout",
                    "content_type_or_parse",
                    "retryable_external_failure"
                ],
                "final_failure_only_after_all_candidates_fail": True,
            },
            "constraints": {
                "must_be_reusable": True,
                "must_return_schema_compatible_output": True,
                "must_not_log_secrets": True,
                "must_not_perform_irreversible_actions_without_confirmation": True,
                "must_define_retry_and_timeout_when_using_network": True,
                "must_use_real_network_when_external_data_is_required": True,
                "must_include_request_response_evidence": True,
                "must_declare_execution_claims": True,
                "must_include_live_verification_metadata": True,
                "must_generate_parameter_mapping_from_runtime_semantics": True,
                "must_not_assume_fixed_domain_fields": True,
                "must_include_valid_implementation_metadata": True,
                "must_define_run_payload_entrypoint": True,
                "must_generate_tool_py_file": True,
                "must_not_register_blueprint_as_executable": True,
                "no_mock_data": True,
            },
            "expected_contract": {
                "tool_id": "string",
                "manifest": "tool.json compatible object with execution_claims, api_discovery, verification",
                "files": {"tool.py": "python source code"},
            },
        }
        compact_generation_request = self.evidence_noise_reducer.compact_generation_request(generation_request)
        await event_bus.emit(run_id, {
            "type": "RUNTIME_TOOL_GENERATION_STARTED",
            "title": "Runtime tool generation started",
            "message": f"Generating reusable tool artifact for capability={capability}",
            "node_id": node_id,
            "step_id": step_id,
            "result": compact_generation_request,
        })
        try:
            artifact = await self.artifact_generator.generate_artifact(
                run_id=run_id,
                node_id=node_id,
                generation_request=compact_generation_request,
            )
            if not isinstance(artifact, dict) or not artifact.get("files"):
                await event_bus.emit(run_id, {
                    "type": "RUNTIME_TOOL_GENERATION_FAILED",
                    "title": "Runtime tool generation failed",
                    "message": "Generated artifact was empty or invalid.",
                    "node_id": node_id,
                    "step_id": step_id,
                    "result": artifact,
                })
                return None
            cost_snapshot = self.runtime_cost_policy.snapshot(state)
            verification = self.sandbox_verifier.verify_tool_artifact(
                artifact=artifact,
                test_input=self._build_tool_input(
                    step=step, run_id=run_id, node_id=node_id, step_id=step_id, user_input=state.get("input", "")
                ),
                allow_network=bool(((artifact.get("manifest") or {}).get("execution_claims") or {}).get("uses_network") or artifact.get("uses_network")),
                timeout_seconds=cost_snapshot.sandbox_timeout_seconds,
            )
            artifact.setdefault("verification", {})["sandbox_verification"] = verification
            await event_bus.emit(run_id, {
                "type": "RUNTIME_TOOL_SANDBOX_VERIFICATION_DONE",
                "title": "Runtime tool sandbox verification completed",
                "message": f"status={verification.get('status')}",
                "node_id": node_id,
                "step_id": step_id,
                "result": verification,
            })
            if not verification.get("safe_to_register") and verification.get("status") != "passed":
                fallback_tool = await self._try_generate_web_extraction_fallback_tool(
                    run_id=run_id,
                    node_id=node_id,
                    step_id=step_id,
                    capability=capability,
                    step=step,
                    state=state,
                    base_generation_request=generation_request,
                    api_discovery=api_discovery,
                    external_discovery=external_discovery,
                    failed_verification=verification,
                )
                if fallback_tool:
                    return fallback_tool
                return {
                    "__runtime_blocked__": True,
                    "status": "sandbox_verification_failed",
                    "reason": verification.get("reason", "Sandbox verification failed."),
                    "discovery": {"api_discovery": api_discovery, "external_solution_discovery": external_discovery},
                    "verification": verification,
                }
            installed = self.artifact_installer.install_artifact(
                artifact=artifact,
                capability=capability,
                source_step=step,
                user_input=state.get("input", ""),
            )
            await event_bus.emit(run_id, {
                "type": "RUNTIME_TOOL_GENERATED_AND_REGISTERED",
                "title": "Runtime tool generated and registered",
                "message": f"Reusable runtime tool registered for capability={capability}",
                "node_id": node_id,
                "step_id": step_id,
                "result": self._public_tool_spec(installed),
            })
            return installed
        except Exception as exc:
            await event_bus.emit(run_id, {
                "type": "RUNTIME_TOOL_GENERATION_FAILED",
                "title": "Runtime tool generation failed",
                "message": str(exc),
                "node_id": node_id,
                "step_id": step_id,
            })
            return None


    async def _try_generate_web_extraction_fallback_tool(
        self,
        *,
        run_id: str,
        node_id: str,
        step_id: str,
        capability: str,
        step: dict[str, Any],
        state: dict[str, Any],
        base_generation_request: dict[str, Any],
        api_discovery: dict[str, Any],
        external_discovery: dict[str, Any],
        failed_verification: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Generate a generic extraction fallback when a JSON/API tool fails.

        The method is domain-neutral. It uses endpoint verification and fetched
        documentation/page evidence to request an alternate artifact type. It
        does not choose providers or hardcode extraction selectors in ai_core.
        """
        endpoint_verification = api_discovery.get("endpoint_verification") if isinstance(api_discovery, dict) else {}
        recommended_type = str((endpoint_verification or {}).get("recommended_tool_type") or "").strip()
        if recommended_type not in {"web_extract", "browser_automation", "external_solution_discovery"}:
            return None

        fallback_request = dict(base_generation_request)
        fallback_constraints = dict(fallback_request.get("constraints") or {})
        fallback_constraints.update({
            "force_runtime_strategy": recommended_type,
            "must_not_assume_json_api_when_endpoint_verification_failed": True,
            "must_use_documentation_or_page_evidence_for_extraction": True,
            "must_use_standard_library_when_possible": True,
            "must_not_use_blocked_primitives": True,
        })
        fallback_request["constraints"] = fallback_constraints
        fallback_request["request_type"] = "runtime_tool_artifact_generation_fallback"
        fallback_request["runtime_fallback"] = {
            "reason": "primary_artifact_failed_verification",
            "failed_verification": failed_verification,
            "endpoint_verification": endpoint_verification,
            "recommended_tool_type": recommended_type,
            "instruction": (
                "Generate a replacement artifact using the recommended runtime strategy. "
                "If the verified endpoint is an HTML page, extract from the supplied page/document evidence. "
                "Do not claim JSON API support unless endpoint verification contains verified_json_api=true."
            ),
        }

        tool_input = self._build_tool_input(
            step=step, run_id=run_id, node_id=node_id, step_id=step_id, user_input=state.get("input", "")
        )

        # For page-extraction fallbacks, first try the deterministic generic
        # adapter. This avoids sending huge discovery JSON to an external LLM
        # when the runtime already has usable no-key evidence.
        if recommended_type in {"web_extract", "browser_automation"}:
            deterministic = await self._build_and_verify_generic_web_extract_tool(
                run_id=run_id, node_id=node_id, step_id=step_id, capability=capability,
                step=step, state=state, api_discovery=api_discovery, external_discovery=external_discovery,
                candidate=None, tool_input=tool_input, reason="deterministic_first_for_web_fallback",
            )
            if deterministic:
                return deterministic

        compact_fallback_request = self.evidence_noise_reducer.compact_generation_request(fallback_request)
        await event_bus.emit(run_id, {
            "type": "RUNTIME_TOOL_FALLBACK_GENERATION_STARTED",
            "title": "Runtime fallback tool generation started",
            "message": f"Generating fallback artifact using strategy={recommended_type}",
            "node_id": node_id,
            "step_id": step_id,
            "result": compact_fallback_request,
        })
        try:
            artifact = await self.artifact_generator.generate_artifact(
                run_id=run_id,
                node_id=node_id,
                generation_request=compact_fallback_request,
            )
            if not isinstance(artifact, dict) or not artifact.get("files"):
                deterministic = await self._build_and_verify_generic_web_extract_tool(
                    run_id=run_id, node_id=node_id, step_id=step_id, capability=capability,
                    step=step, state=state, api_discovery=api_discovery, external_discovery=external_discovery,
                    candidate=None, tool_input=tool_input, reason="llm_fallback_artifact_empty",
                )
                return deterministic
            verification = self.sandbox_verifier.verify_tool_artifact(
                artifact=artifact,
                test_input=tool_input,
                allow_network=True,
            )
            artifact.setdefault("verification", {})["fallback_sandbox_verification"] = verification
            await event_bus.emit(run_id, {
                "type": "RUNTIME_TOOL_FALLBACK_SANDBOX_DONE",
                "title": "Runtime fallback sandbox verification completed",
                "message": f"status={verification.get('status')}",
                "node_id": node_id,
                "step_id": step_id,
                "result": verification,
            })
            if not verification.get("safe_to_register") and verification.get("status") != "passed":
                deterministic = await self._build_and_verify_generic_web_extract_tool(
                    run_id=run_id, node_id=node_id, step_id=step_id, capability=capability,
                    step=step, state=state, api_discovery=api_discovery, external_discovery=external_discovery,
                    candidate=None, tool_input=tool_input, reason="llm_fallback_sandbox_failed",
                )
                return deterministic
            installed = self.artifact_installer.install_artifact(
                artifact=artifact,
                capability=capability,
                source_step=step,
                user_input=state.get("input", ""),
            )
            installed.setdefault("runtime_fallback", {})["strategy"] = recommended_type
            await event_bus.emit(run_id, {
                "type": "RUNTIME_TOOL_FALLBACK_REGISTERED",
                "title": "Runtime fallback tool registered",
                "message": f"Registered fallback runtime tool for capability={capability}",
                "node_id": node_id,
                "step_id": step_id,
                "result": self._public_tool_spec(installed),
            })
            return installed
        except Exception as exc:
            await event_bus.emit(run_id, {
                "type": "RUNTIME_TOOL_FALLBACK_GENERATION_FAILED",
                "title": "Runtime fallback generation failed",
                "message": str(exc),
                "node_id": node_id,
                "step_id": step_id,
            })
            return None


    async def _build_and_verify_generic_web_extract_tool(
        self,
        *,
        run_id: str,
        node_id: str,
        step_id: str,
        capability: str,
        step: dict[str, Any],
        state: dict[str, Any],
        api_discovery: dict[str, Any],
        external_discovery: dict[str, Any],
        candidate: dict[str, Any] | None,
        tool_input: dict[str, Any],
        reason: str,
    ) -> dict[str, Any] | None:
        """Build a deterministic generic HTML/text extraction tool and verify it.

        This is a generic safety net for cases where the LLM-generated adapter
        is structurally invalid. It does not contain business logic. It only
        uses candidate URL/evidence and already-parsed runtime parameters.
        """
        selected = candidate or self._select_generic_web_candidate(api_discovery, external_discovery)
        if not selected:
            return None
        artifact = self._build_generic_web_extract_artifact(
            capability=capability,
            step=step,
            candidate=selected,
            api_discovery=api_discovery,
            external_discovery=external_discovery,
            reason=reason,
        )
        cost_snapshot = self.runtime_cost_policy.snapshot(state)
        verification = self.sandbox_verifier.verify_tool_artifact(
            artifact=artifact,
            test_input=tool_input,
            allow_network=True,
            timeout_seconds=cost_snapshot.sandbox_timeout_seconds,
        )
        artifact.setdefault("verification", {})["generic_web_extract_sandbox_verification"] = verification
        await event_bus.emit(run_id, {
            "type": "GENERIC_WEB_EXTRACT_SANDBOX_DONE",
            "title": "Generic web extraction sandbox completed",
            "message": f"status={verification.get('status')}",
            "node_id": node_id,
            "step_id": step_id,
            "result": {"candidate": selected, "verification": verification},
        })
        if not verification.get("safe_to_register") and verification.get("status") != "passed":
            return None
        installed = self.artifact_installer.install_artifact(
            artifact=artifact,
            capability=capability,
            source_step=step,
            user_input=state.get("input", ""),
        )
        installed.setdefault("runtime_fallback", {})["strategy"] = "deterministic_generic_web_extract"
        await event_bus.emit(run_id, {
            "type": "GENERIC_WEB_EXTRACT_REGISTERED",
            "title": "Generic web extraction tool registered",
            "message": f"Registered generic web extraction runtime tool for capability={capability}",
            "node_id": node_id,
            "step_id": step_id,
            "result": self._public_tool_spec(installed),
        })
        return installed


    def _select_generic_web_candidate(self, api_discovery: dict[str, Any], external_discovery: dict[str, Any]) -> dict[str, Any] | None:
        raw = self.candidate_extractor.extract(api_discovery or {}, external_discovery or {})
        candidates = self.candidate_scorer.score_candidates(raw)
        constraints = self.evidence_noise_reducer.extract_required_terms({"api_discovery": api_discovery, "external_solution_discovery": external_discovery})
        ranked: list[tuple[float, dict[str, Any]]] = []
        for candidate in candidates:
            if str(candidate.get("tool_type") or "") not in {"html_extract", "browser_extract", "json_api"}:
                continue
            evidence_text = self._candidate_evidence_text(candidate)
            score = self.evidence_noise_reducer.score_evidence_item(
                {"url": candidate.get("url"), "title": candidate.get("name"), "text": evidence_text, "source": candidate.get("source"), "rank": candidate.get("rank"), "status": 200},
                constraints=constraints,
                max_text_per_item=1200,
            )
            combined = float(candidate.get("score") or 0) + float(score.get("confidence") or 0) * 100 + float(score.get("coverage", {}).get("coverage_ratio") or 0) * 100
            if score.get("coverage", {}).get("passed") or float(score.get("confidence") or 0) >= 0.45:
                candidate = dict(candidate)
                candidate["evidence_selection"] = score
                ranked.append((combined, candidate))
        ranked.sort(key=lambda x: x[0], reverse=True)
        if ranked:
            return ranked[0][1]
        for candidate in candidates:
            if str(candidate.get("tool_type") or "") in {"html_extract", "browser_extract"}:
                return candidate
        return candidates[0] if candidates else None


    def _build_generic_web_extract_artifact(
        self,
        *,
        capability: str,
        step: dict[str, Any],
        candidate: dict[str, Any],
        api_discovery: dict[str, Any],
        external_discovery: dict[str, Any],
        reason: str,
    ) -> dict[str, Any]:
        evidence_text = self._candidate_evidence_text(candidate)
        artifact = self.generic_web_extract_factory.build_artifact(
            capability=capability,
            candidate=candidate,
            source_step=step,
            evidence_text=evidence_text,
        )
        compact_discovery = self.evidence_noise_reducer.compact_generation_request({
            "api_discovery": api_discovery or {},
            "external_solution_discovery": external_discovery or {},
            "step": step,
        })
        artifact.setdefault("manifest", {})["compact_discovery"] = make_json_safe(compact_discovery)
        artifact.setdefault("manifest", {})["runtime_fallback_reason"] = reason
        artifact.setdefault("verification", {})["runtime_fallback_reason"] = reason
        return artifact


    def _candidate_evidence_text(self, candidate: dict[str, Any]) -> str:
        evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
        chunks: list[str] = []
        for container in (evidence, evidence.get("document") if isinstance(evidence.get("document"), dict) else {}, evidence.get("source_search_result") if isinstance(evidence.get("source_search_result"), dict) else {}):
            if not isinstance(container, dict):
                continue
            for key in ("text_excerpt", "snippet", "sample", "title", "description"):
                value = container.get(key)
                if isinstance(value, str) and value.strip():
                    chunks.append(value.strip())
        light = candidate.get("light_verification") if isinstance(candidate.get("light_verification"), dict) else {}
        sample = light.get("sample")
        if isinstance(sample, str) and sample.strip():
            chunks.append(sample.strip())
        return "\n".join(chunks)[:60000]


    async def _try_repair_executable_tool(
        self,
        *,
        run_id: str,
        node_id: str,
        step_id: str,
        capability: str,
        step: dict[str, Any],
        state: dict[str, Any],
        failed_tool: dict[str, Any],
        failed_result: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Repair a generated runtime tool once when execution fails.

        This remains generic. ai_core does not know why the capability exists or
        which API should be used. It only sends the runtime failure, tool spec,
        and source step back to the runtime code-generation route and installs a
        complete replacement artifact.
        """
        error = failed_result.get("error") if isinstance(failed_result.get("error"), dict) else failed_result
        generation_request = {
            "request_type": "runtime_tool_artifact_repair",
            "capability": capability,
            "step": step,
            "user_input": state.get("input", ""),
            "failed_tool": self._public_tool_spec(failed_tool),
            "failed_result": failed_result,
            "constraints": {
                "must_be_reusable": True,
                "must_return_schema_compatible_output": True,
                "must_not_log_secrets": True,
                "must_not_perform_irreversible_actions_without_confirmation": True,
                "must_define_retry_and_timeout_when_using_network": True,
                "no_mock_data": True,
                "must_define_all_called_functions": True,
            },
            "expected_contract": {
                "tool_id": "string",
                "manifest": "tool.json compatible object",
                "files": {"tool.py": "python source code"},
            },
        }
        await event_bus.emit(run_id, {
            "type": "RUNTIME_TOOL_REPAIR_STARTED",
            "title": "Runtime tool repair started",
            "message": f"Repairing generated tool for capability={capability}: {error}",
            "node_id": node_id,
            "step_id": step_id,
            "result": generation_request,
        })
        try:
            artifact = await self.artifact_generator.repair_artifact(
                run_id=run_id,
                node_id=node_id,
                generation_request=generation_request,
                failed_artifact={"tool": failed_tool},
                error=error,
            )
            cost_snapshot = self.runtime_cost_policy.snapshot(state)
            verification = self.sandbox_verifier.verify_tool_artifact(
                artifact=artifact,
                test_input=self._build_tool_input(
                    step=step, run_id=run_id, node_id=node_id, step_id=step_id, user_input=state.get("input", "")
                ),
                allow_network=bool(((artifact.get("manifest") or {}).get("execution_claims") or {}).get("uses_network") or artifact.get("uses_network")),
                timeout_seconds=cost_snapshot.sandbox_timeout_seconds,
            )
            artifact.setdefault("verification", {})["sandbox_verification"] = verification
            if not verification.get("safe_to_register") and verification.get("status") != "passed":
                await event_bus.emit(run_id, {
                    "type": "RUNTIME_TOOL_REPAIR_BLOCKED",
                    "title": "Runtime tool repair blocked",
                    "message": verification.get("reason", "Sandbox verification failed."),
                    "node_id": node_id,
                    "step_id": step_id,
                    "result": verification,
                })
                return None
            installed = self.artifact_installer.install_artifact(
                artifact=artifact,
                capability=capability,
                source_step=step,
                user_input=state.get("input", ""),
            )
            await event_bus.emit(run_id, {
                "type": "RUNTIME_TOOL_REPAIRED_AND_REGISTERED",
                "title": "Runtime tool repaired and registered",
                "message": f"Repaired reusable runtime tool for capability={capability}",
                "node_id": node_id,
                "step_id": step_id,
                "result": self._public_tool_spec(installed),
            })
            return installed
        except Exception as exc:
            await event_bus.emit(run_id, {
                "type": "RUNTIME_TOOL_REPAIR_FAILED",
                "title": "Runtime tool repair failed",
                "message": str(exc),
                "node_id": node_id,
                "step_id": step_id,
            })
            return None



    async def _try_answer_evidence_fallback_after_module_failure(
        self,
        *,
        run_id: str,
        node_id: str,
        step_id: str,
        capability: str,
        step: dict[str, Any],
        state: dict[str, Any],
        failed_result: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Try direct answer evidence after a registered module fails.

        v70.13 rule:
        - A stale or broken registered module is only one candidate.
        - Its failure must not immediately block the workflow.
        - For answer-lookup requests, run a lightweight web evidence path first.
        - Only if evidence is insufficient should normal API/tool/codegen continue.

        This method intentionally does not inspect domain-specific fields. It uses
        runtime parameters and the generic evidence coverage/sufficiency machinery.
        """
        await event_bus.emit(run_id, {
            "type": "MODULE_FAILURE_EVIDENCE_FALLBACK_STARTED",
            "title": "Module failure evidence fallback started",
            "message": "Registered module failed; checking answer evidence before API/code generation.",
            "node_id": node_id,
            "step_id": step_id,
            "result": {"failed_result": failed_result},
        })
        try:
            if not self.execution_continuation.should_continue_with_evidence(failed_result):
                return None
            external_discovery = await self.external_discovery.discover(
                run_id=run_id,
                node_id=node_id,
                capability=capability,
                step=step,
                user_input=state.get("input", ""),
            )
            if not self.execution_continuation.has_evidence_candidates(external_discovery):
                return None
            direct_execution = await self._try_direct_evidence_execution_from_discovery(
                run_id=run_id,
                node_id=node_id,
                step_id=step_id,
                capability=capability,
                step=step,
                state=state,
                api_discovery={},
                external_discovery=external_discovery,
                reason="after_registered_module_failure_before_api_discovery",
            )
            if direct_execution and direct_execution.get("status") == "success":
                tool_input = self._build_tool_input(
                    step=step,
                    run_id=run_id,
                    node_id=node_id,
                    step_id=step_id,
                    user_input=state.get("input", ""),
                )
                await event_bus.emit(run_id, {
                    "type": "MODULE_FAILURE_EVIDENCE_FALLBACK_SELECTED",
                    "title": "Module failure evidence fallback selected",
                    "message": "Using answer evidence instead of blocking on a failed registered module.",
                    "node_id": node_id,
                    "step_id": step_id,
                    "result": self._compact_direct_result_for_event(direct_execution.get("result") or {}),
                })
                return {
                    "tool": direct_execution.get("tool") or {"id": "evidence_direct_answer", "source": "runtime_research_evidence"},
                    "input": tool_input,
                    "result": direct_execution.get("result"),
                }
        except Exception as exc:
            await event_bus.emit(run_id, {
                "type": "MODULE_FAILURE_EVIDENCE_FALLBACK_FAILED",
                "title": "Module failure evidence fallback failed",
                "message": str(exc),
                "node_id": node_id,
                "step_id": step_id,
            })
            return None

        await event_bus.emit(run_id, {
            "type": "MODULE_FAILURE_EVIDENCE_FALLBACK_INSUFFICIENT",
            "title": "Module failure evidence fallback insufficient",
            "message": "Answer evidence was insufficient; continuing with normal API/tool/codegen path.",
            "node_id": node_id,
            "step_id": step_id,
        })
        return None


    async def _try_direct_evidence_execution_from_discovery(
        self,
        *,
        run_id: str,
        node_id: str,
        step_id: str,
        capability: str,
        step: dict[str, Any],
        state: dict[str, Any],
        api_discovery: dict[str, Any],
        external_discovery: dict[str, Any],
        reason: str,
    ) -> dict[str, Any] | None:
        """Execute the evidence pipeline before generated components.

        v70.24 turns this method into a real state-machine branch:
        candidate evidence -> sufficiency gate -> optional page fetch -> DOM/text
        extraction -> structured result material.  It does not branch on any
        domain term; all matching is based on runtime parameters and generic
        textual/structural evidence.
        """
        tool_input = self._build_tool_input(
            step=step,
            run_id=run_id,
            node_id=node_id,
            step_id=step_id,
            user_input=state.get("input", ""),
        )
        known_parameters = self._runtime_known_parameters(tool_input)
        raw_candidates = self.candidate_extractor.extract(api_discovery or {}, external_discovery or {})
        scored_candidates = self.candidate_scorer.score_candidates(raw_candidates)
        no_key_candidates = [c for c in scored_candidates if not self._candidate_requires_credential(c)]
        if not no_key_candidates:
            await event_bus.emit(run_id, {
                "type": "EVIDENCE_PIPELINE_NO_PUBLIC_CANDIDATES",
                "title": "Evidence pipeline found no public candidates",
                "message": "No non-credential candidates were available for evidence execution.",
                "node_id": node_id,
                "step_id": step_id,
                "result": {"reason": reason},
            })
            return None

        sufficiency = self.answer_sufficiency.evaluate(
            user_input=str(state.get("input") or ""),
            objective=str(step.get("objective") or ""),
            capability=str(capability or ""),
            known_parameters=known_parameters,
            evidence=no_key_candidates,
        )
        await event_bus.emit(run_id, {
            "type": "EVIDENCE_PIPELINE_SUFFICIENCY_EVALUATED",
            "title": "Evidence pipeline sufficiency evaluated",
            "message": f"stage=candidates passed={sufficiency.get('passed')} next_action={sufficiency.get('next_action')}",
            "node_id": node_id,
            "step_id": step_id,
            "result": self._compact_sufficiency_for_event(sufficiency),
        })

        working_candidates = no_key_candidates
        # For browser/web evidence, candidate snippets are not answer material.
        # Always fetch and materialize selected pages before allowing direct
        # evidence synthesis. This prevents the location-only sufficiency gate
        # from accepting raw search results and bypassing Playwright/CDP capture.
        should_fetch_pages = (
            sufficiency.get("next_action") == "fetch_selected_pages"
            or str(reason or "").find("web") >= 0
            or any(str(c.get("tool_type") or "") in {"html_extract", "web_evidence"} for c in no_key_candidates if isinstance(c, dict))
        )
        if should_fetch_pages:
            # Deep materialization must see the full public candidate set, not only
            # the first snippet selected by the preliminary sufficiency scorer.
            # The scorer is allowed to rank, but not to shrink the evidence pool
            # before multi-source convergence has run.
            fetched_documents = await self._fetch_selected_pages_for_evidence(
                run_id=run_id,
                node_id=node_id,
                step_id=step_id,
                selected_evidence=no_key_candidates,
                known_parameters=known_parameters,
                state=state,
                objective=str(step.get("objective") or ""),
            )
            if fetched_documents:
                fetched_candidates = self.candidate_extractor.extract({"documents": fetched_documents})
                # Prefer materialized browser/deep-search documents over raw
                # candidate snippets. Raw snippets remain fallback only.
                working_candidates = self.candidate_scorer.score_candidates(fetched_candidates) or self.candidate_scorer.score_candidates(fetched_candidates + no_key_candidates)
                sufficiency = self.answer_sufficiency.evaluate(
                    user_input=str(state.get("input") or ""),
                    objective=str(step.get("objective") or ""),
                    capability=str(capability or ""),
                    known_parameters=known_parameters,
                    evidence=working_candidates,
                )
                await event_bus.emit(run_id, {
                    "type": "EVIDENCE_PIPELINE_SUFFICIENCY_EVALUATED",
                    "title": "Evidence pipeline sufficiency evaluated",
                    "message": f"stage=fetched_pages passed={sufficiency.get('passed')} next_action={sufficiency.get('next_action')}",
                    "node_id": node_id,
                    "step_id": step_id,
                    "result": self._compact_sufficiency_for_event(sufficiency),
                })

        if not sufficiency.get("passed"):
            partial_result = self._build_incomplete_evidence_result(
                working_candidates=working_candidates,
                known_parameters=known_parameters,
                reason="evidence_sufficiency_not_met",
                sufficiency=sufficiency,
                state=state,
            )
            await event_bus.emit(run_id, {
                "type": "EVIDENCE_PIPELINE_INSUFFICIENT",
                "title": "Evidence pipeline insufficient",
                "message": "Generic evidence did not cover the runtime request sufficiently; returning an investigation report instead of unrelated fallback.",
                "node_id": node_id,
                "step_id": step_id,
                "result": self._compact_sufficiency_for_event(sufficiency),
            })
            return {
                "__direct_execution_result__": True,
                "status": "partial",
                "tool": {"id": "browser_network_deepsearch", "source": "browser_or_web_structured_evidence"},
                "result": partial_result,
            }

        direct_result = self.evidence_direct_answer.build(
            candidates=working_candidates,
            payload=tool_input,
            capability=capability,
            attempts=[],
            state=state,
        )
        if not direct_result or not self.result_classifier.classify(direct_result).get("success"):
            partial_result = self._build_incomplete_evidence_result(
                working_candidates=working_candidates,
                known_parameters=known_parameters,
                reason="materialization_not_available",
                sufficiency=sufficiency,
                state=state,
            )
            await event_bus.emit(run_id, {
                "type": "EVIDENCE_PIPELINE_MATERIALIZATION_FAILED",
                "title": "Evidence pipeline materialization failed",
                "message": "Evidence was sufficient, but structured answer material could not be created; returning the source investigation report.",
                "node_id": node_id,
                "step_id": step_id,
                "result": self._compact_sufficiency_for_event(sufficiency),
            })
            return {
                "__direct_execution_result__": True,
                "status": "partial",
                "tool": {"id": "browser_network_deepsearch", "source": "browser_or_web_structured_evidence"},
                "result": partial_result,
            }
        direct_data = direct_result.get("data") if isinstance(direct_result.get("data"), dict) else {}
        material_quality = direct_data.get("answer_material_quality") if isinstance(direct_data.get("answer_material_quality"), dict) else {}
        consensus_eval = direct_data.get("consensus_evaluation") if isinstance(direct_data.get("consensus_evaluation"), dict) else {}
        if material_quality.get("passed") is False or (
            consensus_eval and consensus_eval.get("passed") is not True
        ):
            partial_result = self._build_incomplete_evidence_result(
                working_candidates=working_candidates,
                known_parameters=known_parameters,
                reason="consensus_not_ready",
                sufficiency=sufficiency,
                state=state,
                direct_result=direct_result,
            )
            await event_bus.emit(run_id, {
                "type": "EVIDENCE_PIPELINE_CONSENSUS_NOT_READY",
                "title": "Evidence consensus not ready",
                "message": "Materialized evidence did not satisfy the generic convergence contract; returning the source investigation report.",
                "node_id": node_id,
                "step_id": step_id,
                "result": {
                    "quality": material_quality,
                    "consensus_evaluation": consensus_eval,
                    "sufficiency": self._compact_sufficiency_for_event(sufficiency),
                },
            })
            return {
                "__direct_execution_result__": True,
                "status": "partial",
                "tool": {"id": "browser_network_deepsearch", "source": "browser_or_web_structured_evidence"},
                "result": partial_result,
            }

        data = direct_result.setdefault("data", {})
        data["answer_sufficiency"] = sufficiency
        data["structured_materialized"] = True
        direct_result.setdefault("fallback", {})["direct_evidence_before_tool_generation"] = {
            "reason": reason,
            "candidate_count": len(working_candidates),
            "policy": "evidence_pipeline_before_generated_components",
        }
        await event_bus.emit(run_id, {
            "type": "DIRECT_EVIDENCE_EXECUTION_SELECTED",
            "title": "Direct evidence execution selected",
            "message": "Using evidence-backed material before generated component execution.",
            "node_id": node_id,
            "step_id": step_id,
            "result": {
                "tool": {"id": "browser_network_deepsearch", "source": "browser_or_web_structured_evidence"},
                "candidate_count": len(working_candidates),
                "reason": reason,
                "result_summary": self._compact_direct_result_for_event(direct_result),
            },
        })
        return {
            "__direct_execution_result__": True,
            "status": "success",
            "tool": {"id": "browser_network_deepsearch", "source": "browser_or_web_structured_evidence"},
            "result": direct_result,
        }

    async def _fetch_selected_pages_for_evidence(
        self,
        *,
        run_id: str,
        node_id: str,
        step_id: str,
        selected_evidence: list[dict[str, Any]],
        known_parameters: dict[str, Any] | None = None,
        state: dict[str, Any] | None = None,
        objective: str = "",
    ) -> list[dict[str, Any]]:
        state = state if isinstance(state, dict) else {}
        known_parameters = known_parameters if isinstance(known_parameters, dict) else {}
        cost_snapshot = self.runtime_cost_policy.snapshot(state)
        await event_bus.emit(run_id, {
            "type": "DEEP_WEB_RESEARCH_STARTED",
            "title": "Deep web research started",
            "message": "Planning, fetching, extracting, reducing, and validating web evidence before synthesis.",
            "node_id": node_id,
            "step_id": step_id,
            "result": {"candidate_count": len(selected_evidence), "policy": cost_snapshot.evidence_policy()},
        })
        try:
            result = await asyncio.wait_for(
                self.deep_web_research.run(
                    candidates=selected_evidence,
                    known=known_parameters,
                    state=state,
                    objective=objective,
                    policy=cost_snapshot.evidence_policy(),
                ),
                timeout=cost_snapshot.stage_timeout("extraction", 45),
            )
        except Exception as exc:
            await event_bus.emit(run_id, {
                "type": "DEEP_WEB_RESEARCH_FAILED",
                "title": "Deep web research failed",
                "message": str(exc),
                "node_id": node_id,
                "step_id": step_id,
            })
            return []
        data = result.get("data") if isinstance(result, dict) else {}
        data = data if isinstance(data, dict) else {}
        await event_bus.emit(run_id, {
            "type": "DEEP_WEB_RESEARCH_COMPLETED",
            "title": "Deep web research completed",
            "message": "Web evidence was converted into compact answer material.",
            "node_id": node_id,
            "step_id": step_id,
            "result": {
                "quality": data.get("answer_material_quality"),
                "fact_count": len(data.get("normalized_facts") or []),
                "trace": data.get("deep_research_trace"),
            },
        })
        if not data:
            return []
        return [{
            "source": "deep_web_research_material",
            "document": {
                "status": "success",
                "title": "Deep web research material",
                "url": "",
                "text_excerpt": str(data.get("answer_material") or ""),
                "visible_text_excerpt": str(data.get("answer_material") or ""),
                "normalized_facts": data.get("normalized_facts") or [],
                "selected_evidence_blocks": data.get("selected_evidence_blocks") or [],
                "answer_material_quality": data.get("answer_material_quality") or {},
                "consensus_evaluation": data.get("consensus_evaluation") or {},
                "source_summaries": data.get("source_summaries") or [],
                "deep_research_trace": data.get("deep_research_trace") or {},
            },
        }]

    def _runtime_known_parameters(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Collect runtime parameters without dropping arrays or normalized objects.

        The evidence pipeline is schema-driven: all downstream validation depends
        on the complete target contract.  Lists and dictionaries therefore must
        be preserved instead of being silently discarded.
        """
        known: dict[str, Any] = {}
        if not isinstance(payload, dict):
            return known

        def merge(source: Any) -> None:
            if not isinstance(source, dict):
                return
            for key, value in source.items():
                key_s = str(key)
                if key_s in {"context", "source_step", "parameters", "known", "optional"}:
                    continue
                if value is None or value == "":
                    continue
                if isinstance(value, (str, int, float, bool)):
                    known[key_s] = value
                elif isinstance(value, (list, tuple, set)):
                    cleaned = [self._compact_runtime_value(v) for v in value]
                    cleaned = [v for v in cleaned if v not in (None, "", [], {})]
                    if cleaned:
                        known[key_s] = cleaned
                elif isinstance(value, dict):
                    compact = self._compact_runtime_value(value)
                    if compact not in (None, "", [], {}):
                        known[key_s] = compact

        params = payload.get("parameters") if isinstance(payload.get("parameters"), dict) else {}
        source_step = payload.get("source_step") if isinstance(payload.get("source_step"), dict) else {}
        source_params = source_step.get("parameters") if isinstance(source_step.get("parameters"), dict) else {}
        intent_ref = source_step.get("intent_contract_ref") if isinstance(source_step.get("intent_contract_ref"), dict) else {}

        for source in (
            payload.get("known") if isinstance(payload.get("known"), dict) else {},
            params.get("known") if isinstance(params.get("known"), dict) else {},
            source_params.get("known") if isinstance(source_params.get("known"), dict) else {},
            intent_ref,
            payload,
        ):
            merge(source)

        return known

    def _compact_runtime_value(self, value: Any) -> Any:
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, (list, tuple, set)):
            return [self._compact_runtime_value(v) for v in value]
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for k, v in value.items():
                if v in (None, ""):
                    continue
                out[str(k)] = self._compact_runtime_value(v)
            if "normalized_value" in out and len(out) <= 3:
                return out.get("normalized_value")
            return out
        return str(value)

    def _evidence_url(self, item: dict[str, Any]) -> str:
        if not isinstance(item, dict):
            return ""
        for key in ("url", "official_documentation_url"):
            value = item.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return value
        for nested_key in ("evidence", "document", "source_search_result"):
            nested = item.get(nested_key) if isinstance(item.get(nested_key), dict) else None
            if nested:
                value = self._evidence_url(nested)
                if value:
                    return value
        return ""

    def _compact_sufficiency_for_event(self, sufficiency: dict[str, Any]) -> dict[str, Any]:
        selected = sufficiency.get("selected_evidence") if isinstance(sufficiency.get("selected_evidence"), list) else []
        return {
            "passed": sufficiency.get("passed"),
            "score": sufficiency.get("score"),
            "min_score": sufficiency.get("min_score"),
            "aggregate_coverage": sufficiency.get("aggregate_coverage"),
            "aggregate_answer_signal": sufficiency.get("aggregate_answer_signal"),
            "fetch_candidate_count": sufficiency.get("fetch_candidate_count"),
            "next_action": sufficiency.get("next_action"),
            "reason": sufficiency.get("reason"),
            "selected_evidence": [
                {"url": x.get("url"), "title": x.get("title"), "score": x.get("score")}
                for x in selected[:5]
                if isinstance(x, dict)
            ],
        }

    def _compact_direct_result_for_event(self, result: dict[str, Any]) -> dict[str, Any]:
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        material = str(data.get("answer_material") or "")
        return {
            "status": result.get("status"),
            "source": result.get("source"),
            "source_url": data.get("source_url"),
            "source_title": data.get("source_title"),
            "known_parameters": data.get("known_parameters"),
            "answer_material_preview": material[:1000],
        }


    async def _try_multi_candidate_fallback_execution(
        self,
        *,
        run_id: str,
        node_id: str,
        step_id: str,
        capability: str,
        step: dict[str, Any],
        state: dict[str, Any],
        failed_tool: dict[str, Any],
        failed_result: dict[str, Any],
        tool_input: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Parallel candidate verification and result synthesis.

        v68 upgrade. This method is domain-neutral: it does not know providers,
        APIs, or business categories. It extracts runtime candidates, scores them,
        prioritizes no-credential candidates, verifies several usable candidates
        in parallel, executes successful adapters, and synthesizes the best result
        based on evidence quality and candidate reliability. Credential-protected
        candidates become a human-interaction choice only when no usable no-key
        path succeeds.
        """
        initial_classification = self.result_classifier.classify(failed_result)
        if initial_classification.get("success"):
            return {"status": "success", "tool": failed_tool, "result": failed_result, "attempts": []}

        await event_bus.emit(run_id, {
            "type": "PARALLEL_CANDIDATE_EVALUATION_STARTED",
            "title": "Parallel candidate evaluation started",
            "message": f"Initial execution failed with category={initial_classification.get('category')}; evaluating alternate candidates.",
            "node_id": node_id,
            "step_id": step_id,
            "result": {"initial_failure": initial_classification},
        })

        api_discovery = None
        tool_discovery = failed_tool.get("api_discovery") if isinstance(failed_tool.get("api_discovery"), dict) else None
        if tool_discovery:
            api_discovery = tool_discovery
        else:
            try:
                api_discovery = await self.api_discovery.discover(
                    run_id=run_id,
                    node_id=node_id,
                    capability=capability,
                    step=step,
                    user_input=state.get("input", ""),
                )
            except Exception as exc:
                api_discovery = {"status": "discovery_failed", "error": {"message": str(exc)}}

        try:
            external_discovery = await self.external_discovery.discover(
                run_id=run_id,
                node_id=node_id,
                capability=capability,
                step=step,
                user_input=state.get("input", ""),
            )
        except Exception as exc:
            external_discovery = {"status": "external_discovery_failed", "error": {"message": str(exc)}}

        raw_candidates = self.candidate_extractor.extract(api_discovery or {}, external_discovery or {}, failed_tool or {})
        candidates = self.candidate_scorer.score_candidates(raw_candidates)
        await event_bus.emit(run_id, {
            "type": "CANDIDATE_STRATEGY_SELECTION_DONE",
            "title": "Candidate strategy selection completed",
            "message": f"Scored {len(candidates)} candidate(s).",
            "node_id": node_id,
            "step_id": step_id,
            "result": {"candidates": candidates[:12]},
        })
        if not candidates:
            return {"status": "no_candidates", "attempts": []}

        credential_candidates = [c for c in candidates if self._candidate_requires_credential(c)]
        no_key_candidates = [c for c in candidates if not self._candidate_requires_credential(c)]
        cost_snapshot = self.runtime_cost_policy.snapshot(state)
        max_parallel = max(1, cost_snapshot.max_generated_component_attempts)
        max_total = max(1, cost_snapshot.max_generated_component_attempts)
        attempt_candidates = no_key_candidates[:max_parallel]
        credential_attempts = [self._credential_skip_attempt(i + 1, c) for i, c in enumerate(credential_candidates[:max_total])]

        await event_bus.emit(run_id, {
            "type": "CANDIDATE_PARALLEL_PLAN_READY",
            "title": "Candidate parallel plan ready",
            "message": f"no_key={len(no_key_candidates)} credential_required={len(credential_candidates)} parallel={len(attempt_candidates)}",
            "node_id": node_id,
            "step_id": step_id,
            "result": {
                "no_key_candidates": no_key_candidates[:max_parallel],
                "credential_candidates": credential_candidates[:4],
                "policy": "no_key_first_parallel_then_credential_choice",
            },
        })

        tasks = [
            self._attempt_runtime_candidate(
                run_id=run_id,
                node_id=node_id,
                step_id=step_id,
                capability=capability,
                step=step,
                state=state,
                tool_input=tool_input,
                candidate=candidate,
                attempt_index=index,
                api_discovery=api_discovery or {},
                external_discovery=external_discovery or {},
                failed_result=failed_result,
                initial_classification=initial_classification,
            )
            for index, candidate in enumerate(attempt_candidates, start=1)
        ]
        attempts: list[dict[str, Any]] = []
        if tasks:
            try:
                gathered = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=cost_snapshot.operation_timeout_seconds)
            except asyncio.TimeoutError:
                gathered = [TimeoutError("candidate evaluation timeout") for _ in tasks]
            for index, item in enumerate(gathered, start=1):
                if isinstance(item, BaseException):
                    candidate = attempt_candidates[index - 1]
                    attempt = {"attempt_index": index, "candidate": candidate, "status": "exception", "error": {"message": str(item)}}
                else:
                    attempt = item
                if isinstance(attempt, dict):
                    attempts.append(attempt)
                    candidate = attempt.get("candidate") if isinstance(attempt.get("candidate"), dict) else {}
                    classification = attempt.get("classification") if isinstance(attempt.get("classification"), dict) else {}
                    self.provider_reliability.record_attempt(candidate=candidate, status=str(attempt.get("status") or "unknown"), classification=classification)

        attempts.extend(credential_attempts)
        synthesized = self.candidate_synthesizer.choose(attempts)
        if synthesized and synthesized.get("status") == "success":
            selected_attempt = next((a for a in attempts if a.get("attempt_index") == ((synthesized.get("result") or {}).get("fallback") or {}).get("parallel_candidate_evaluation", {}).get("selected_attempt_index")), None)
            self.strategy_memory.record_success(capability=capability, step=step, attempt=selected_attempt, result=synthesized.get("result") or {})
            await event_bus.emit(run_id, {
                "type": "PARALLEL_CANDIDATE_SYNTHESIS_DONE",
                "title": "Parallel candidate synthesis completed",
                "message": "Selected best successful candidate result.",
                "node_id": node_id,
                "step_id": step_id,
                "result": {"attempts": self._compact_attempts(attempts), "selected": ((synthesized.get("result") or {}).get("fallback") or {}).get("parallel_candidate_evaluation")},
            })
            return synthesized

        direct_result = self.evidence_direct_answer.build(
            candidates=no_key_candidates,
            payload=tool_input,
            capability=capability,
            attempts=attempts,
            state=state,
        )
        if direct_result and self.result_classifier.classify(direct_result).get("success"):
            direct_result.setdefault("fallback", {})["no_key_evidence_direct_answer"] = {
                "reason": "Code-generated adapters failed, but no-credential verified evidence covered the runtime parameters.",
                "attempts": self._compact_attempts(attempts),
                "credential_candidates_available": len(credential_candidates),
                "api_key_interaction_required": False,
            }
            await event_bus.emit(run_id, {
                "type": "NO_KEY_EVIDENCE_DIRECT_ANSWER_SELECTED",
                "title": "No-key evidence answer selected",
                "message": "Using verified no-credential evidence instead of requesting an API key.",
                "node_id": node_id,
                "step_id": step_id,
                "result": {"result": direct_result, "attempts": self._compact_attempts(attempts)},
            })
            return {"status": "success", "tool": {"id": "evidence_direct_answer", "source": "runtime_research_evidence"}, "result": direct_result, "attempts": attempts}

        if credential_candidates and not any(a.get("status") == "success" for a in attempts):
            return {
                "status": "optional_human_interaction_available",
                "attempts": attempts,
                "human_interaction": {
                    "type": "credential_optional_upgrade",
                    "title": "Optional API Key Available",
                    "message": "A credential-protected provider may improve the result. You can provide an API key or continue without it.",
                    "reason": "No no-credential candidate produced a validated executable result. You may provide a credential for protected candidates, or continue without an API key using the best available no-key evidence or error summary.",
                    "required": False,
                    "api_sources": [self._compact_candidate_for_interaction(c) for c in credential_candidates[:5]],
                    "fields": {"credential": {"label": "API Key / Credential", "secret": True, "required": False, "placeholder": "Paste API key here"}},
                    "secret_fields": [
                        {"name": (self._compact_candidate_for_interaction(credential_candidates[0]).get("secret_key") if credential_candidates else "runtime_access_key"), "label": f"{(self._compact_candidate_for_interaction(credential_candidates[0]).get('provider') if credential_candidates else 'Provider')} access key", "interaction_type": "secret", "required": False, "placeholder": f"Paste key for {(self._compact_candidate_for_interaction(credential_candidates[0]).get('provider') if credential_candidates else 'provider')}", "provider": (self._compact_candidate_for_interaction(credential_candidates[0]).get("provider") if credential_candidates else None), "source_url": (self._compact_candidate_for_interaction(credential_candidates[0]).get("url") if credential_candidates else None)}
                    ],
                    "actions": [
                        {"id": "continue_without_key", "label": "Continue without API key"},
                        {"id": "provide_credential", "label": "Provide API key and continue"},
                    ],
                    "options": [
                        {"id": "continue_without_key", "label": "Continue without API key"},
                        {"id": "provide_credential", "label": "Provide API key and continue"},
                    ],
                    "candidates": [self._compact_candidate_for_interaction(c) for c in credential_candidates[:5]],
                },
            }

        await event_bus.emit(run_id, {
            "type": "PARALLEL_CANDIDATE_EVALUATION_EXHAUSTED",
            "title": "All evaluated candidates failed",
            "message": f"Evaluated {len(attempts)} candidate attempt(s); none produced validated output.",
            "node_id": node_id,
            "step_id": step_id,
            "result": {"attempts": self._compact_attempts(attempts)},
        })
        return {"status": "all_candidates_failed", "attempts": attempts}

    async def _attempt_runtime_candidate(
        self,
        *,
        run_id: str,
        node_id: str,
        step_id: str,
        capability: str,
        step: dict[str, Any],
        state: dict[str, Any],
        tool_input: dict[str, Any],
        candidate: dict[str, Any],
        attempt_index: int,
        api_discovery: dict[str, Any],
        external_discovery: dict[str, Any],
        failed_result: dict[str, Any],
        initial_classification: dict[str, Any],
    ) -> dict[str, Any]:
        await event_bus.emit(run_id, {
            "type": "CANDIDATE_ATTEMPT_STARTED",
            "title": "Candidate attempt started",
            "message": f"Parallel attempt {attempt_index}",
            "node_id": node_id,
            "step_id": step_id,
            "result": {"candidate": candidate},
        })
        generation_request = {
            "request_type": "runtime_tool_artifact_generation_candidate_parallel",
            "capability": capability,
            "step": step,
            "user_input": state.get("input", ""),
            "tool_input": tool_input,
            "candidate_attempt": {
                "attempt_index": attempt_index,
                "candidate": candidate,
                "tool_type": candidate.get("tool_type"),
                "score": candidate.get("score"),
                "light_verification": candidate.get("light_verification"),
                "previous_failure": failed_result,
                "previous_failure_classification": initial_classification,
            },
            "candidate_strategy": {
                "tool_type": candidate.get("tool_type"),
                "score": candidate.get("score"),
                "score_reasons": candidate.get("score_reasons", []),
                "light_verification": candidate.get("light_verification"),
                "selection_policy": "parallel_no_key_first_evidence_scored",
            },
            "api_discovery": api_discovery or {},
            "external_solution_discovery": external_discovery or {},
            "documentation_understanding": (api_discovery.get("result") or {}).get("documentation_understanding", {}) if isinstance(api_discovery, dict) else {},
            "constraints": {
                "must_generate_adapter_for_this_candidate_only": True,
                "must_define_network_timeout": True,
                "must_return_error_instead_of_raising": True,
                "must_return_json_serializable_dict": True,
                "must_not_use_mock_data": True,
                "must_include_source_provenance": True,
                "must_not_claim_success_when_response_contains_error": True,
                "must_expose_entrypoint_run_payload_dict": True,
                "must_use_standard_library_unless_requirements_declared": True,
                "must_not_return_error_payload_as_success": True,
                "must_map_extracted_or_api_data_to_output_schema": True,
                "must_include_valid_implementation_metadata": True,
                "must_define_run_payload_entrypoint": True,
                "must_generate_tool_py_file": True,
                "if_candidate_returns_html_generate_extraction_adapter": True,
                "if_candidate_requires_unavailable_authentication_skip_with_structured_error": True,
            },
            "expected_contract": {
                "tool_id": "string",
                "manifest": "tool.json compatible object",
                "files": {"tool.py": "python source code exposing run(payload: dict) -> dict"},
            },
        }
        attempt_record: dict[str, Any] = {"attempt_index": attempt_index, "candidate": candidate}
        try:
            artifact = await self.artifact_generator.generate_artifact(run_id=run_id, node_id=node_id, generation_request=generation_request)
            if not self._artifact_has_valid_contract_shape(artifact):
                artifact = self._build_generic_web_extract_artifact(
                    capability=capability, step=step, candidate=candidate,
                    api_discovery=api_discovery or {}, external_discovery=external_discovery or {},
                    reason="llm_candidate_artifact_contract_invalid",
                )

            verification = self.sandbox_verifier.verify_tool_artifact(artifact=artifact, test_input=tool_input, allow_network=True)
            attempt_record["verification"] = verification
            if not verification.get("safe_to_register") and verification.get("status") != "passed":
                deterministic_artifact = self._build_generic_web_extract_artifact(
                    capability=capability, step=step, candidate=candidate,
                    api_discovery=api_discovery or {}, external_discovery=external_discovery or {},
                    reason="sandbox_or_contract_failed",
                )
                deterministic_verification = self.sandbox_verifier.verify_tool_artifact(artifact=deterministic_artifact, test_input=tool_input, allow_network=True)
                attempt_record["deterministic_verification"] = deterministic_verification
                if deterministic_verification.get("safe_to_register") or deterministic_verification.get("status") == "passed":
                    artifact = deterministic_artifact
                    verification = deterministic_verification
                    attempt_record["verification"] = verification
                    attempt_record["used_deterministic_adapter"] = True
                else:
                    attempt_record.update({"status": "sandbox_verification_failed", "classification": {"success": False, "category": "sandbox_verification_failed"}})
                    return attempt_record

            installed = self.artifact_installer.install_artifact(artifact=artifact, capability=capability, source_step=step, user_input=state.get("input", ""))
            result = self.tool_runner.run_tool(installed, tool_input, run_id=run_id, node_id=node_id, step_id=step_id, capability=capability)
            result = self._enforce_evidence_quality(result, tool_input)
            classification = self.result_classifier.classify(result)
            attempt_record.update({
                "status": "success" if classification.get("success") else "failed",
                "classification": classification,
                "tool": self._public_tool_spec(installed),
                "installed_tool": installed,
                "result": result,
            })
            await event_bus.emit(run_id, {
                "type": "CANDIDATE_ATTEMPT_DONE",
                "title": "Candidate attempt completed",
                "message": f"status={attempt_record['status']} category={classification.get('category')}",
                "node_id": node_id,
                "step_id": step_id,
                "result": {**attempt_record, "installed_tool": self._public_tool_spec(installed)},
            })
            return attempt_record
        except Exception as exc:
            attempt_record.update({"status": "exception", "classification": {"success": False, "category": "exception"}, "error": {"message": str(exc)}})
            return attempt_record

    def _credential_skip_attempt(self, attempt_index: int, candidate: dict[str, Any]) -> dict[str, Any]:
        return {
            "attempt_index": attempt_index,
            "candidate": candidate,
            "status": "credential_required_skipped_by_default",
            "classification": {"success": False, "category": "credential_required"},
            "error": {"code": "credential_required", "message": "Candidate requires a credential. No-credential candidates are evaluated first."},
        }

    def _compact_candidate_for_interaction(self, candidate: dict[str, Any]) -> dict[str, Any]:
        source_url = candidate.get("url") or candidate.get("official_documentation_url")
        provider_name = candidate.get("provider") or candidate.get("provider_name") or candidate.get("name") or candidate.get("title")
        secret_key = (
            candidate.get("secret_key")
            or candidate.get("required_secret")
            or candidate.get("required_secret_key")
            or candidate.get("api_key_name")
            or candidate.get("credential_name")
            or "runtime_access_key"
        )
        return make_json_safe({
            "name": candidate.get("name"),
            "title": candidate.get("title"),
            "provider": provider_name,
            "url": source_url,
            "source": candidate.get("source"),
            "tool_type": candidate.get("tool_type"),
            "secret_key": secret_key,
            "requires_credential": self._candidate_requires_credential(candidate),
            "score": candidate.get("score"),
            "score_reasons": candidate.get("score_reasons"),
        })

    def _artifact_has_valid_contract_shape(self, artifact: Any) -> bool:
        if not isinstance(artifact, dict):
            return False
        files = artifact.get("files") if isinstance(artifact.get("files"), dict) else {}
        manifest = artifact.get("manifest") if isinstance(artifact.get("manifest"), dict) else {}
        implementation = manifest.get("implementation") if isinstance(manifest.get("implementation"), dict) else {}
        code = str(files.get("tool.py") or "")
        return bool(code.strip() and "def run(" in code and implementation.get("function") == "run" and implementation.get("type"))

    def _enforce_evidence_quality(self, result: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        """Convert low-quality success payloads into retryable structured errors.

        This is generic: it only checks that answer material covers runtime
        parameters already present in the payload and is not just sample/demo
        material. It does not know any business-specific terms.
        """
        if not isinstance(result, dict) or result.get("status") != "success":
            return result
        quality = self.evidence_quality.validate_result(result, payload)
        result.setdefault("quality", {})["evidence"] = quality
        if quality.get("passed"):
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            if isinstance(data, dict):
                data.setdefault("answer_material_quality", quality)
            return result
        return {
            "status": "error",
            "error": {
                "code": "answer_material_quality_failed",
                "message": "Extracted answer material did not cover the runtime parameters or looked like sample/demo data.",
                "details": quality,
            },
            "data": result.get("data") if isinstance(result.get("data"), dict) else {},
            "source": result.get("source") or "runtime_quality_gate",
            "requires_human_confirmation": False,
            "quality": {"evidence": quality},
            "previous_result_status": "success",
        }

    def _candidate_requires_credential(self, candidate: dict[str, Any]) -> bool:
        if not isinstance(candidate, dict):
            return False
        if candidate.get("requires_api_key") is True or candidate.get("requires_authentication") is True:
            return True
        text = " ".join(str(candidate.get(k) or "") for k in ("name", "title", "url", "official_documentation_url", "notes")).lower()
        reasons = " ".join(str(x) for x in candidate.get("score_reasons", []) if isinstance(x, str)).lower()
        verification = candidate.get("light_verification") if isinstance(candidate.get("light_verification"), dict) else {}
        if verification.get("requires_authentication") is True:
            return True
        text_markers = ("api key", "your_api_key", "appid", "requires api key")
        if any(marker in text for marker in text_markers):
            return True
        # Score reasons are symbolic labels. Match them exactly so a positive
        # label such as "no_api_key_required_or_not_detected" is not
        # misclassified as credential-protected merely because it contains the
        # substring "api_key_required".
        reason_values = {str(x).strip().lower() for x in candidate.get("score_reasons", []) if isinstance(x, str)}
        return bool(reason_values.intersection({"authentication_required", "api_key_required", "credential_required"}))

    def _compact_attempts(self, attempts: Any) -> list[dict[str, Any]]:
        """Return non-recursive attempt summaries safe for result/provenance output."""
        if not isinstance(attempts, list):
            return []
        compact: list[dict[str, Any]] = []
        for item in attempts:
            if not isinstance(item, dict):
                continue
            candidate = item.get("candidate") if isinstance(item.get("candidate"), dict) else {}
            classification = item.get("classification") if isinstance(item.get("classification"), dict) else {}
            verification = item.get("verification") if isinstance(item.get("verification"), dict) else {}
            error = item.get("error") if isinstance(item.get("error"), dict) else None
            compact.append(make_json_safe({
                "attempt_index": item.get("attempt_index"),
                "status": item.get("status"),
                "candidate": {
                    "name": candidate.get("name"),
                    "url": candidate.get("url") or candidate.get("official_documentation_url"),
                    "source": candidate.get("source"),
                    "tool_type": candidate.get("tool_type"),
                    "score": candidate.get("score"),
                    "score_reasons": candidate.get("score_reasons"),
                },
                "verification": {
                    "status": verification.get("status"),
                    "safe_to_register": verification.get("safe_to_register"),
                    "reason": verification.get("reason"),
                },
                "classification": classification,
                "error": error,
            }))
        return compact

    def _requires_confirmation(self, step: dict[str, Any], tool: dict[str, Any], state: dict[str, Any]) -> bool:
        confirmations = state.get("human_confirmations") if isinstance(state, dict) else []
        step_id = str(step.get("step_id") or step.get("task_id") or "")
        if isinstance(confirmations, list):
            for item in confirmations:
                if isinstance(item, dict):
                    holds = item.get("safety_holds") if isinstance(item.get("safety_holds"), list) else []
                    if any(str(h.get("step_id", "")) == step_id for h in holds if isinstance(h, dict)):
                        return False

        tool_safety = tool.get("safety") if isinstance(tool.get("safety"), dict) else {}
        step_safety = step.get("safety") if isinstance(step.get("safety"), dict) else {}
        runtime_safety = {**step_safety, **tool_safety}

        # Runtime/tool safety declaration is authoritative. This avoids treating
        # a model's generic requires_human_confirmation=true as business logic.
        if runtime_safety.get("requires_human_confirmation") is False:
            return False
        if runtime_safety.get("can_perform_irreversible_action") is True:
            return True
        if runtime_safety.get("can_write_external_data") is True:
            return True
        if runtime_safety.get("requires_human_confirmation") is True:
            return True
        return bool(step.get("requires_human_confirmation", False) and runtime_safety)


    def _has_executable_implementation(self, tool: dict[str, Any]) -> bool:
        status = str(tool.get("status", "")).lower().strip()
        if status in {"missing_implementation_blueprint_generated", "blueprint_generated", "pending", "draft", "disabled"}:
            return False
        implementation = tool.get("implementation")
        if not isinstance(implementation, dict):
            return False
        impl_type = str(implementation.get("type") or "").lower().strip()
        if impl_type not in {"python_function", "python_module", "runtime_python"}:
            return False
        if not (implementation.get("module_path") or implementation.get("path")):
            return False
        if not (implementation.get("function") or implementation.get("callable") or "run"):
            return False
        return True

    def _public_tool_spec(self, tool: dict[str, Any]) -> dict[str, Any]:
        public = dict(tool)
        implementation = public.get("implementation")
        if isinstance(implementation, dict):
            public["implementation"] = {
                "type": implementation.get("type"),
                "function": implementation.get("function") or implementation.get("callable") or "run",
                "module_path": implementation.get("module_path") or implementation.get("path"),
            }
        return public


    def _execute_runtime_observation_code(self) -> str:
        """Run a tiny generated local program for generic runtime observation.

        This keeps runtime-native observation on the code-execution path instead
        of web evidence.  The generated code is domain-neutral and only reads the
        local runtime clock.  If command execution is unavailable, the caller
        falls back to an in-process equivalent.
        """
        code = (
            "import json\n"
            "from datetime import datetime, timezone\n"
            "print(json.dumps({'value': datetime.now(timezone.utc).astimezone().isoformat()}))\n"
        )
        try:
            completed = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if completed.returncode != 0:
                return ""
            payload = json.loads((completed.stdout or "").strip() or "{}")
            value = payload.get("value") if isinstance(payload, dict) else ""
            return str(value or "").strip()
        except Exception:
            return ""

    def _try_runtime_native_observation(
        self,
        *,
        run_id: str,
        node_id: str,
        step_id: str,
        capability: str,
        step: dict[str, Any],
        state: dict[str, Any],
        normalized_plan: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Execute a generic native-observation step when the runtime plan asks for it.

        The core does not infer business meaning here. It only honors generic
        runtime-generated source/capability contracts such as source_level or
        execution_strategy. The returned fact is generic and can be rewritten by
        synthesis according to the user request.
        """
        if not self._step_requests_runtime_native(step, normalized_plan, capability):
            return None
        observed_at = self._execute_runtime_observation_code() or datetime.now(timezone.utc).astimezone().isoformat()
        fact = {
            "kind": "observed_value",
            "label": "runtime_observation",
            "value": observed_at,
            "unit": "",
            "context": "runtime native observation",
            "confidence": 0.98,
            "source_level": "runtime_native",
            "source": "runtime_native",
            "structured": True,
        }
        return {
            "input": {
                "run_id": run_id,
                "node_id": node_id,
                "step_id": step_id,
                "capability": capability,
                "source_step": step,
            },
            "result": {
                "status": "success",
                "source": "runtime_native_observation",
                "data": {
                    "normalized_facts": [fact],
                    "source_url": "",
                    "source_title": "runtime_native",
                    "execution_mode": "runtime_generated_code",
                    "runtime_generated_code_executed": True,
                },
                "provenance": {
                    "source": "runtime_native",
                    "execution_claims": {
                        "real_execution_declared": True,
                        "no_mock_data_declared": True,
                        "network_declared": False,
                        "live_verification_passed": True,
                        "evidence_quality_passed": True,
                    },
                },
            },
        }

    def _step_requests_runtime_native(self, step: dict[str, Any], normalized_plan: dict[str, Any], capability: str) -> bool:
        candidates: list[Any] = [
            capability,
            step.get("required_source_level"),
            step.get("source_level"),
            step.get("source_policy"),
            step.get("execution_strategy"),
            step.get("runtime_semantic_contract"),
            normalized_plan.get("runtime_semantic_contract") if isinstance(normalized_plan, dict) else None,
        ]
        params = step.get("parameters") if isinstance(step.get("parameters"), dict) else {}
        candidates.extend([params.get("source_level"), params.get("source_policy"), params.get("execution_strategy")])
        text = self._generic_contract_text(candidates)
        return "runtime_native" in text or "primary_runtime" in text or "native_observation" in text

    def _generic_contract_text(self, values: list[Any]) -> str:
        parts: list[str] = []
        for value in values:
            if isinstance(value, str):
                parts.append(value)
            elif isinstance(value, dict):
                parts.extend(str(k) for k in value.keys())
                parts.extend(str(v) for v in value.values() if isinstance(v, (str, int, float, bool)))
            elif isinstance(value, list):
                parts.extend(str(v) for v in value if isinstance(v, (str, int, float, bool)))
        return " ".join(parts).casefold()

    def _repair_single_step_before_execution(self, step: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        """Last-chance generic repair for one runtime-generated step.

        This is intentionally domain-neutral. It does not decide what the task
        means; it only applies the same runtime structural repair policy to the
        current step and returns the repaired step when available.
        """
        try:
            repaired_plan = self.execution_state_repair.repair(
                {"planned_steps": [step]},
                runtime_context=state.get("runtime_context") if isinstance(state.get("runtime_context"), dict) else {},
            )
            repaired_steps = repaired_plan.get("planned_steps")
            if isinstance(repaired_steps, list) and repaired_steps and isinstance(repaired_steps[0], dict):
                return repaired_steps[0]
        except Exception:
            return step
        return step

    def _capability_name(self, value: Any) -> str | None:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            for key in ["capability", "capability_id", "capability_action", "action", "name", "id"]:
                candidate = value.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()
        return None

    def _normalize_human_interaction(self, value: Any) -> dict[str, Any]:
        if isinstance(value, bool):
            return {"required": value}
        if isinstance(value, dict):
            normalized = dict(value)
            fields = normalized.get("fields")
            has_fields = bool(fields) if isinstance(fields, (list, dict)) else False
            interaction_type = str(normalized.get("type") or "").lower().strip()
            confirmation_like = interaction_type in {"confirmation", "human_confirmation", "approval"}

            # Do not treat unrelated metadata such as
            # {"requires_confirmation": false} as a human-input request.
            if "required" in normalized:
                required = bool(normalized.get("required"))
            elif confirmation_like:
                required = bool(normalized.get("requires_confirmation", True))
            else:
                required = has_fields

            normalized["required"] = required
            if not required and not has_fields:
                normalized.setdefault("fields", {})
                normalized.setdefault("type", "none")
            return normalized
        return {"required": False, "type": "none", "fields": {}}

    def _missing_fields(self, step: dict[str, Any]) -> list[str]:
        return self.state_consistency.missing_fields(step)

    def _build_credential_interaction_payload(self, *, interaction: dict[str, Any], step_id: str, step: dict[str, Any], required: bool) -> dict[str, Any]:
        """Build an English UI contract for optional credential input.

        Credential-protected candidates are treated as optional upgrades unless
        the runtime has no no-key path and cannot continue without user choice.
        The UI always offers two choices: provide a secret or continue without it.
        """
        fields = interaction.get("fields") if isinstance(interaction.get("fields"), dict) else {}
        candidates = interaction.get("candidates") if isinstance(interaction.get("candidates"), list) else []
        first_candidate = candidates[0] if candidates and isinstance(candidates[0], dict) else {}
        api_sources = []
        for item in candidates[:5]:
            if not isinstance(item, dict):
                continue
            api_sources.append({
                "provider": item.get("provider") or item.get("name") or item.get("title") or "credential-protected source",
                "url": item.get("url"),
                "source": item.get("source"),
                "tool_type": item.get("tool_type"),
                "secret_key": item.get("secret_key") or "runtime_access_key",
            })
        source_label = first_candidate.get("provider") or first_candidate.get("name") or first_candidate.get("title") or "credential-protected source"
        source_url = first_candidate.get("url")
        secret_key = first_candidate.get("secret_key") or "runtime_access_key"
        default_secret_fields = [
            {
                "name": secret_key,
                "label": f"{source_label} access key",
                "interaction_type": "secret",
                "required": False,
                "placeholder": f"Paste key for {source_label}",
                "provider": source_label,
                "source_url": source_url,
                "secret_key": secret_key,
            }
        ]
        return {
            "step_id": step_id,
            "type": "credential_optional_upgrade",
            "required": bool(required),
            "title": interaction.get("title") or "Optional API Key Available",
            "message": interaction.get("message") or "A credential-protected provider may improve the result. You can provide an API key or continue without it.",
            "objective": step.get("objective"),
            "reason": interaction.get("reason") or "Credential-protected candidates are optional upgrades and must not block no-key execution paths.",
            "provider": source_label,
            "api_source": {"provider": source_label, "url": source_url, "secret_key": secret_key},
            "api_sources": api_sources,
            "fields": fields,
            "secret_fields": interaction.get("secret_fields") or default_secret_fields,
            "actions": interaction.get("actions") or [
                {"id": "continue_without_key", "label": "Continue without API key"},
                {"id": "provide_credential", "label": "Provide API key and continue"},
            ],
            "options": interaction.get("options") or [
                {"id": "continue_without_key", "label": "Continue without API key"},
                {"id": "provide_credential", "label": "Provide API key and continue"},
            ],
            "candidates": candidates,
            "source_step": step,
        }

    def _execution_budget_exhausted(self, started_at: datetime, timeout_seconds: int) -> bool:
        try:
            elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
            return elapsed >= max(1, int(timeout_seconds))
        except Exception:
            return False

    def _overall_status(self, execution_steps, blocked_steps, human_interactions, missing_tools, safety_holds, optional_human_interactions=None) -> str:
        if any(bool(item.get("required", True)) for item in human_interactions if isinstance(item, dict)):
            return "waiting_for_human_information"
        if optional_human_interactions and not any(step.get("status") == "executed" for step in execution_steps):
            return "waiting_optional_upgrade"
        if missing_tools:
            return "missing_tool_implementation"
        if safety_holds:
            return "waiting_for_human_confirmation"
        if blocked_steps and not execution_steps:
            return "blocked"
        if blocked_steps and any(step.get("status") in {"tool_execution_failed", "module_execution_failed"} for step in execution_steps):
            return "tool_execution_failed"
        if execution_steps and blocked_steps:
            return "partially_executed"
        if execution_steps and all(step.get("status") in {"executed", "skipped"} for step in execution_steps):
            return "executed"
        if execution_steps:
            return "ready"
        return "no_executable_steps"
