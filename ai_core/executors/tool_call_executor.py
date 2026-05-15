from __future__ import annotations

import asyncio
from typing import Any

from ai_core.events.event_bus import event_bus
from ai_core.runtime.provenance import ExecutionProvenanceRecorder
from ai_core.tools.runtime_tool_registry import RuntimeToolRegistry
from ai_core.modules.module_builder import RuntimeModuleBuilder
from ai_core.modules.module_loader import RuntimeModuleLoader
from ai_core.modules.autonomous_codegen_executor import AutonomousCodegenExecutor
from ai_core.modules.module_artifact_generator import RuntimeModuleArtifactGenerator
from ai_core.modules.runtime_generated_module_installer import RuntimeGeneratedModuleInstaller
from ai_core.workflow.workflow_normalizer import WorkflowNormalizer
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
from ai_core.execution.evidence_direct_answer import EvidenceDirectAnswerBuilder
from ai_core.context.evidence_noise_reducer import EvidenceNoiseReducer
from ai_core.knowledge.knowledge_service import KnowledgeService
from ai_core.utils.safe_json import make_json_safe


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
        workflow_plan = previous_results.get("workflow_planning", {})
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

        for index, step in enumerate(planned_steps):
            step_id = str(step.get("step_id") or step.get("task_id") or f"step_{index + 1}")
            # v57: perform a final per-step structural repair immediately before
            # execution decisions. This prevents stale or over-blocked planner output
            # from bypassing the global repair stage. The logic remains generic and
            # only uses runtime-configured structural policies.
            step = self._repair_single_step_before_execution(step, state)
            step = self.state_consistency.repair_step(step)
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

            # v70.9 priority layer: local/model knowledge first.
            # If previous successful runtime knowledge already covers the current
            # parameters, answer from local knowledge and avoid web/API/codegen.
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
                        "message": "Registered module failed execution; continuing with web/evidence/codegen fallback chain.",
                        "node_id": node_id,
                        "step_id": step_id,
                        "result": {"module": module_record, "failure": module_result},
                    })
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
                            "tool": {"id": "evidence_direct_answer", "source": "runtime_research_evidence"},
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
                            execution_steps.append({
                                "step_id": step_id,
                                "status": "executed" if self._is_success_result(normalized_module_result) else "module_execution_failed",
                                "module": module_result.get("registry_record"),
                                "input": module_input,
                                "result": normalized_module_result,
                                "provenance": normalized_module_result.get("provenance") if isinstance(normalized_module_result, dict) else None,
                                "source_step": step,
                            })
                            if not self._is_success_result(normalized_module_result):
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

            if tool_result.get("status") != "success":
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
        return None


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
        item = self.knowledge.best_covered(query, required_terms=required_terms, min_score=1.0)
        if not item:
            return None
        result = {
            "status": "success",
            "data": {
                "answer_material": item.get("text_excerpt"),
                "source": item.get("source"),
                "coverage": item.get("coverage"),
                "known_parameters": tool_input.get("known") or (tool_input.get("parameters") or {}).get("known") or {},
                "local_knowledge_used": True,
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
                aliases.extend([f"{y}/{m}/{d}", f"{mi}/{di}", f"{mi}-{di}", f"{d}"])
                if mi == 5:
                    aliases.extend([f"May {di}", f"{di} May", f"{di} May {y}"])
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
        example {"temperature": 25, "condition": "Sunny"}. A missing `status`
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

        tool_input: dict[str, Any] = {}
        for source in (known, optional):
            for key, value in source.items():
                if key not in tool_input:
                    tool_input[str(key)] = value

        tool_input.update({
            "parameters": params,
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
            verification = self.sandbox_verifier.verify_tool_artifact(
                artifact=artifact,
                test_input=self._build_tool_input(
                    step=step, run_id=run_id, node_id=node_id, step_id=step_id, user_input=state.get("input", "")
                ),
                allow_network=bool(((artifact.get("manifest") or {}).get("execution_claims") or {}).get("uses_network") or artifact.get("uses_network")),
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
        verification = self.sandbox_verifier.verify_tool_artifact(
            artifact=artifact,
            test_input=tool_input,
            allow_network=True,
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
            verification = self.sandbox_verifier.verify_tool_artifact(
                artifact=artifact,
                test_input=self._build_tool_input(
                    step=step, run_id=run_id, node_id=node_id, step_id=step_id, user_input=state.get("input", "")
                ),
                allow_network=bool(((artifact.get("manifest") or {}).get("execution_claims") or {}).get("uses_network") or artifact.get("uses_network")),
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
        """Return a direct evidence result before invoking LLM code generation.

        This is intentionally generic. It does not know any domain fields. It
        uses dynamic runtime parameters, candidate extraction/scoring, evidence
        coverage and noise reduction. If the already fetched no-key evidence is
        sufficient, execution should finish directly instead of generating a new
        tool or sending large discovery JSON to a model.
        """
        tool_input = self._build_tool_input(
            step=step,
            run_id=run_id,
            node_id=node_id,
            step_id=step_id,
            user_input=state.get("input", ""),
        )
        raw_candidates = self.candidate_extractor.extract(api_discovery or {}, external_discovery or {})
        scored_candidates = self.candidate_scorer.score_candidates(raw_candidates)
        no_key_candidates = [c for c in scored_candidates if not self._candidate_requires_credential(c)]
        if not no_key_candidates:
            return None

        direct_result = self.evidence_direct_answer.build(
            candidates=no_key_candidates,
            payload=tool_input,
            capability=capability,
            attempts=[],
        )
        if not direct_result or not self.result_classifier.classify(direct_result).get("success"):
            return None

        direct_result.setdefault("fallback", {})["direct_evidence_before_tool_generation"] = {
            "reason": reason,
            "candidate_count": len(no_key_candidates),
            "policy": "answer_from_verified_no_key_evidence_before_llm_codegen",
        }
        await event_bus.emit(run_id, {
            "type": "DIRECT_EVIDENCE_EXECUTION_SELECTED",
            "title": "Direct evidence execution selected",
            "message": "Using covered no-key evidence before runtime tool generation.",
            "node_id": node_id,
            "step_id": step_id,
            "result": {
                "tool": {"id": "evidence_direct_answer", "source": "runtime_research_evidence"},
                "candidate_count": len(no_key_candidates),
                "reason": reason,
                "result_summary": self._compact_direct_result_for_event(direct_result),
            },
        })
        return {
            "__direct_execution_result__": True,
            "status": "success",
            "tool": {"id": "evidence_direct_answer", "source": "runtime_research_evidence"},
            "result": direct_result,
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
        max_parallel = 4
        max_total = 8
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
            gathered = await asyncio.gather(*tasks, return_exceptions=True)
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
                    "fields": {"credential": {"label": "API Key / Credential", "secret": True, "required": False, "placeholder": "Paste API key here"}},
                    "secret_fields": [
                        {"name": "credential", "label": "API Key / Credential", "interaction_type": "secret", "required": False, "placeholder": "Paste API key here"}
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
        return make_json_safe({
            "name": candidate.get("name"),
            "url": candidate.get("url") or candidate.get("official_documentation_url"),
            "source": candidate.get("source"),
            "tool_type": candidate.get("tool_type"),
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
        markers = ("api key", "your_api_key", "appid", "requires api key", "authentication_required", "api_key_required")
        return any(marker in text or marker in reasons for marker in markers)

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
        return {
            "step_id": step_id,
            "type": "credential_optional_upgrade",
            "required": bool(required),
            "title": interaction.get("title") or "Optional API Key Available",
            "message": interaction.get("message") or "A credential-protected provider may improve the result. You can provide an API key or continue without it.",
            "objective": step.get("objective"),
            "reason": interaction.get("reason") or "Credential-protected candidates are optional upgrades and must not block no-key execution paths.",
            "fields": fields,
            "secret_fields": interaction.get("secret_fields") or [
                {
                    "name": "credential",
                    "label": "API Key / Credential",
                    "interaction_type": "secret",
                    "required": False,
                    "placeholder": "Paste API key here",
                }
            ],
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
        if execution_steps and all(step.get("status") == "executed" for step in execution_steps):
            return "executed"
        if execution_steps:
            return "ready"
        return "no_executable_steps"
