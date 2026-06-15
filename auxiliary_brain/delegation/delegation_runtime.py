from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import copy
import json
import mimetypes
import re

from ai_core.agent_delegation import AgentExecutionRequest, AgentExecutionResult, PrimaryBrainDelegationClient
from auxiliary_brain.storage import JsonStore
from auxiliary_brain.runtime import new_id
from auxiliary_brain.delegation.task_mind_graph import TaskMindGraphBuilder
from auxiliary_brain.delegation.workflow_output_resolver import WorkflowOutputResolver
from auxiliary_brain.delegation.output_normalizer import OutputNormalizer
from ai_core.config.paths import RUNTIME_DOWNLOADS
from ai_core.knowledge.knowledge_service import KnowledgeService
from auxiliary_brain.media import ImageGenerationService, VideoGenerationService
from auxiliary_brain.parameters.agent_parameter_contract import AgentParameterContractService
from auxiliary_brain.runtime_tools.runtime_registered_tool_service import RuntimeRegisteredToolService
from auxiliary_brain.runtime.capability.registered_tool_parameter_bridge import RegisteredToolParameterBridge


class AgentDelegationRuntime:
    """Coordinates delegation without executing participant work itself.

    This runtime owns coordination state only. It records progress so the Studio
    can show where a long-running delegated execution is currently working.
    Actual participant work and final synthesis are delegated to the primary
    runtime.
    """

    def __init__(self, store: JsonStore | None = None, primary_client: PrimaryBrainDelegationClient | None = None) -> None:
        self.store = store or JsonStore()
        self.primary_client = primary_client or PrimaryBrainDelegationClient()
        self.parameter_contract_service = AgentParameterContractService()
        self.knowledge_service = KnowledgeService()
        self.image_generation_service = ImageGenerationService()
        self.video_generation_service = VideoGenerationService()
        self.registered_tool_service = RuntimeRegisteredToolService()
        self.registered_tool_parameter_bridge = RegisteredToolParameterBridge()
        self.workflow_output_resolver = WorkflowOutputResolver()
        self.output_normalizer = OutputNormalizer()

    async def execute_task(self, task_graph: dict[str, Any], participants: list[dict[str, Any]]) -> dict[str, Any]:
        selected = self._fresh_task_participants(self._select_participants(task_graph, participants))
        selected = self._hydrate_runtime_bindings_for_task(task_graph, selected)
        return await self._execute_task_with_selected(task_graph, selected)

    async def _execute_task_with_selected(self, task_graph: dict[str, Any], selected: list[dict[str, Any]]) -> dict[str, Any]:
        run_id = new_id("delegation_run")
        task_name = str(task_graph.get("task_name") or task_graph.get("graph_id") or "task")
        task_instruction = str(task_graph.get("instruction") or task_graph.get("objective") or "")
        community_id = str(task_graph.get("community_id") or "default")
        runtime_parameters = dict(task_graph.get("runtime_parameters") or {}) if isinstance(task_graph.get("runtime_parameters"), dict) else {}
        source_material = self._task_source_material(task_graph=task_graph, fallback_values=[task_instruction])
        if source_material:
            runtime_parameters.setdefault("_original_user_material", source_material)
            structural_values = self._extract_structural_values_from_material(source_material)
            if structural_values:
                runtime_parameters.setdefault("_detected_structural_values", structural_values)
        task_mind_graph = self._build_task_mind_graph(task_graph, selected)
        dependency_plan = task_mind_graph.get("agent_relation_analysis") or self._build_participant_dependency_plan(task_graph, selected)

        run_payload: dict[str, Any] = {
            "run_id": run_id,
            "origin": "auxiliary_brain",
            "status": "running",
            "graph_id": str(task_graph.get("graph_id") or task_name),
            "task_graph_id": str(task_graph.get("graph_id") or task_name),
            "task_name": task_name,
            "community_id": community_id,
            "started_at": self._now(),
            "current_stage": "preparing_delegation",
            "delegation_policy": "participant_requests_are_executed_by_ai_core",
            "progress_events": [],
            "agent_results": [],
            "participant_dependency_plan": dependency_plan,
            "task_mind_graph": task_mind_graph,
            "graph_self_check": dependency_plan.get("self_check") if isinstance(dependency_plan, dict) else {},
            "repair_plan": (dependency_plan.get("self_check") or {}).get("repair_plan") if isinstance(dependency_plan, dict) and isinstance(dependency_plan.get("self_check"), dict) else [],
            # Keep task-run parameters in the durable run payload.  They are
            # needed when a runtime-registered capability pauses for approval:
            # the approval resume must re-create the same registered-tool
            # invocation without asking the old primary-runtime checkpoint to
            # restore it.  This is task-run state, not persisted agent state.
            "runtime_parameters": runtime_parameters,
        }
        self._record_progress(run_payload, "prepare", "Preparing delegation run", "running")
        self._record_global_mind_graph_progress(run_payload, task_mind_graph)

        # Apply task-scoped parameters before checking missing agent values.
        # Values supplied in the task instruction or resume form belong only to
        # this in-memory run and are not written back to durable agent profiles.
        self._apply_task_runtime_parameters_to_selected(selected, runtime_parameters)
        missing_parameter_fields = self._collect_missing_agent_parameter_fields(selected, dependency_plan=dependency_plan)
        if missing_parameter_fields:
            pending_action = {
                "kind": "agent_parameter_collection",
                "message": "Agent execution requires parameter values before runtime can continue.",
                "request": {
                    "input_mode": "multi_value_list",
                    "fields": missing_parameter_fields,
                },
            }
            run_payload.update({
                "status": "requires_input",
                "current_stage": "waiting_for_agent_parameters",
                "pending_action": pending_action,
                "missing_inputs": missing_parameter_fields,
                "completed_at": self._now(),
            })
            self._record_progress(run_payload, "waiting_agent_parameters", "Waiting for agent parameter values", "waiting")
            self.store.write_json(f"generated/results/{run_id}.json", run_payload)
            return run_payload

        agent_results = []
        execution_order = self._participants_in_mind_graph_order(selected, task_mind_graph)
        for index, participant in enumerate(execution_order):
            participant_id = str(participant.get("participant_id") or participant.get("id") or "").strip()
            participant_name = str(participant.get("display_name") or participant.get("agent_name") or participant.get("name") or participant.get("participant_id") or "participant")
            blocked_by = self._blocked_dependency_ids(
                participant_id=participant_id,
                completed_results=agent_results,
                dependency_plan=dependency_plan,
            )
            if blocked_by:
                result = self._dependency_blocked_result(
                    participant_id=participant_id,
                    participant_name=participant_name,
                    blocked_by=blocked_by,
                )
                result_payload = self._sanitize_result_payload(result.__dict__)
                agent_results.append(result)
                run_payload["agent_results"].append(result_payload)
                self._record_progress(
                    run_payload,
                    f"participant_{index + 1}_blocked",
                    f"Participant blocked by failed dependency: {participant_name}",
                    "failed",
                )
                continue

            self._record_progress(
                run_payload,
                f"participant_{index + 1}_prepare",
                f"Preparing participant: {participant_name}",
                "running",
            )
            self._bind_dependency_outputs_to_participant(
                participant=participant,
                completed_results=agent_results,
                dependency_plan=dependency_plan,
            )
            capability_result = await self._try_execute_generated_capability(
                participant=participant,
                completed_results=agent_results,
                dependency_plan=dependency_plan,
                task_name=task_name,
            )
            if capability_result is not None:
                result = capability_result
                result_payload = self._sanitize_result_payload(result.__dict__)
                agent_results.append(result)
                run_payload["agent_results"].append(result_payload)
                self._record_progress(
                    run_payload,
                    f"participant_{index + 1}_complete",
                    f"Participant finished: {participant_name}",
                    "completed" if result.status == "completed" else result.status,
                )
                if result.status in {"requires_key", "requires_input", "paused"}:
                    run_payload.update({
                        "status": result.status,
                        "current_stage": "waiting_for_required_input",
                        "pending_action": result.pending_action,
                        "missing_inputs": result.missing_inputs or [],
                        "completed_at": self._now(),
                    })
                    self._record_progress(run_payload, "waiting_input", "Waiting for required input", "waiting")
                    self.store.write_json(f"generated/results/{run_id}.json", run_payload)
                    return run_payload
                continue
            request = AgentExecutionRequest(
                participant_id=str(participant.get("participant_id") or participant.get("id")),
                participant_name=participant_name,
                participant_instruction=str(participant.get("execution_objective") or participant.get("instruction") or participant.get("description") or ""),
                task_name=task_name,
                task_instruction=task_instruction,
                community_id=community_id,
                shared_context=self._build_participant_shared_context(
                    task_graph=task_graph,
                    selected=selected,
                    participant=participant,
                    completed_results=agent_results,
                    dependency_plan=dependency_plan,
                    task_mind_graph=task_mind_graph,
                    for_input_parsing=True,
                ),
            )
            result = await self._execute_workflow_step_through_ai_core_with_progress(
                request,
                self._build_primary_runtime_progress_bridge(
                    run_payload,
                    participant_index=index + 1,
                    participant_name=participant_name,
                ),
            )
            result_payload = self._sanitize_result_payload(result.__dict__)
            agent_results.append(result)
            run_payload["agent_results"].append(result_payload)
            self._record_progress(
                run_payload,
                f"participant_{index + 1}_complete",
                f"Participant finished: {participant_name}",
                "completed" if result.status == "completed" else result.status,
            )
            if result.status in {"requires_key", "requires_input", "paused"}:
                run_payload.update({
                    "status": result.status,
                    "current_stage": "waiting_for_required_input",
                    "pending_action": result.pending_action,
                    "missing_inputs": result.missing_inputs or [],
                    "completed_at": self._now(),
                })
                self._record_progress(run_payload, "waiting_input", "Waiting for required input", "waiting")
                self.store.write_json(f"generated/results/{run_id}.json", run_payload)
                return run_payload
            continue
            capability_result = await self._try_execute_generated_capability(
                participant=participant,
                completed_results=agent_results,
                dependency_plan=dependency_plan,
                task_name=task_name,
            )
            if capability_result is not None:
                result = capability_result
                result_payload = self._sanitize_result_payload(result.__dict__)
                agent_results.append(result)
                run_payload["agent_results"].append(result_payload)
                self._record_progress(
                    run_payload,
                    f"participant_{index + 1}_complete",
                    f"Participant finished: {participant_name}",
                    "completed" if result.status == "completed" else result.status,
                )
                if result.status in {"requires_key", "requires_input", "paused"}:
                    run_payload.update({
                        "status": result.status,
                        "current_stage": "waiting_for_required_input",
                        "pending_action": result.pending_action,
                        "missing_inputs": result.missing_inputs or [],
                    })
                    self._record_progress(run_payload, "waiting_input", "Waiting for required input", "waiting")
                    self.store.write_json(f"generated/results/{run_id}.json", run_payload)
                    return run_payload
                continue
            capability_result = await self._try_execute_generated_capability(
                participant=participant,
                completed_results=agent_results,
                dependency_plan=dependency_plan,
                task_name=task_name,
            )
            if capability_result is not None:
                result = capability_result
                result_payload = self._sanitize_result_payload(result.__dict__)
                agent_results.append(result)
                run_payload["agent_results"].append(result_payload)
                self._record_progress(
                    run_payload,
                    f"participant_{index + 1}_complete",
                    f"Participant finished: {participant_name}",
                    "completed" if result.status == "completed" else result.status,
                )
                if result.status in {"requires_key", "requires_input", "paused"}:
                    run_payload.update({
                        "status": result.status,
                        "current_stage": "waiting_for_required_input",
                        "pending_action": result.pending_action,
                        "missing_inputs": result.missing_inputs or [],
                    })
                    self._record_progress(run_payload, "waiting_input", "Waiting for required input", "waiting")
                    self.store.write_json(f"generated/results/{run_id}.json", run_payload)
                    return run_payload
                continue
            material_result = self._try_execute_file_material_generation(
                participant=participant,
                completed_results=agent_results,
                dependency_plan=dependency_plan,
                task_name=task_name,
            )
            if material_result is not None:
                result = material_result
                result_payload = self._sanitize_result_payload(result.__dict__)
                agent_results.append(result)
                run_payload["agent_results"].append(result_payload)
                self._record_progress(
                    run_payload,
                    f"participant_{index + 1}_complete",
                    f"Participant finished: {participant_name}",
                    "completed",
                )
                continue
            shared_context = self._build_participant_shared_context(
                task_graph=task_graph,
                selected=selected,
                participant=participant,
                completed_results=agent_results,
                dependency_plan=dependency_plan,
                task_mind_graph=task_mind_graph,
                for_input_parsing=True,
            )
            request = AgentExecutionRequest(
                participant_id=str(participant.get("participant_id") or participant.get("id")),
                participant_name=participant_name,
                participant_instruction=str(participant.get("execution_objective") or participant.get("instruction") or participant.get("description") or ""),
                task_name=task_name,
                task_instruction=task_instruction,
                community_id=community_id,
                shared_context=shared_context,
            )
            self._record_progress(
                run_payload,
                f"participant_{index + 1}_primary_runtime",
                f"Primary runtime executing participant: {participant_name}",
                "running",
            )
            if self._is_generated_dataflow_step(participant, task_graph):
                material_return = self._try_return_dependency_material(
                    participant=participant,
                    completed_results=agent_results,
                    dependency_plan=dependency_plan,
                )
                if material_return is not None:
                    result = material_return
                else:
                    result = await self._execute_intermediate_step_with_progress(
                        request,
                        self._build_primary_runtime_progress_bridge(
                            run_payload,
                            participant_index=index + 1,
                            participant_name=participant_name,
                        ),
                    )
            else:
                result = await self._execute_agent_request_with_progress(
                    request,
                    self._build_primary_runtime_progress_bridge(
                        run_payload,
                        participant_index=index + 1,
                        participant_name=participant_name,
                    ),
                )
            result_payload = self._sanitize_result_payload(result.__dict__)
            agent_results.append(result)
            run_payload["agent_results"].append(result_payload)
            self._record_progress(
                run_payload,
                f"participant_{index + 1}_complete",
                f"Participant finished: {participant_name}",
                "completed" if result.status == "completed" else result.status,
            )
            if result.status in {"failed", "incomplete", "timeout"}:
                # Do not mark a failed primary-runtime participant as successful.
                # Keep executing remaining participants so the final synthesis can
                # report all failures, but preserve the failure status in payload.
                pass
            if result.status in {"requires_key", "requires_input", "paused"}:
                run_payload.update({
                    "status": result.status,
                    "current_stage": "waiting_for_required_input",
                    "pending_action": result.pending_action,
                    "missing_inputs": result.missing_inputs or [],
                    "completed_at": self._now(),
                })
                self._record_progress(run_payload, "waiting_input", "Waiting for required input", "waiting")
                return run_payload

        run_payload["agent_results"] = self._dedupe_result_payloads(run_payload.get("agent_results") or [])
        agent_results = self._to_agent_results(run_payload["agent_results"])
        synthesis_results = self._terminal_results_for_synthesis(agent_results, task_mind_graph)
        run_payload["synthesis_input_policy"] = {
            "mode": "terminal_graph_outputs",
            "source_result_count": len(agent_results),
            "synthesis_result_count": len(synthesis_results),
        }
        self._record_progress(run_payload, "final_synthesis", "Primary runtime synthesizing delegated results", "running")
        synthesis = await self.primary_client.synthesize_delegated_results(
            task_name=task_name,
            task_instruction=task_instruction,
            agent_results=synthesis_results,
            shared_context={"community_id": community_id, "task_mind_graph": task_mind_graph},
        )
        self._record_progress(run_payload, "final_synthesis_complete", "Final synthesis completed", "completed")
        delivery_id = new_id("delivery")
        delivery_payload = {
            "delivery_id": delivery_id,
            "origin": "auxiliary_brain",
            "upstream_origin": "ai_core",
            "task_name": task_name,
            "run_id": run_id,
            "final_answer": synthesis.get("final_answer"),
            "generated_files": self._collect_generated_files(agent_results),
            "synthesis": synthesis,
            "created_at": self._now(),
        }
        delivery_path = self.store.write_json(f"deliveries/{delivery_id}.json", delivery_payload)

        final_status = str(synthesis.get("status") or "")
        failed_statuses = {"failed", "completed_with_no_participant_result", "partial_failed", "no_usable_result"}
        run_payload.update({
            "status": "failed" if final_status in failed_statuses else "completed",
            "current_stage": "failed" if final_status in failed_statuses else "completed",
            "completed_at": self._now(),
            "synthesis": synthesis,
            "delivery": str(delivery_path),
        })
        self.store.write_json(f"generated/results/{run_id}.json", run_payload)
        return run_payload




    async def _resume_registered_tool_confirmation(
        self,
        *,
        run_payload: dict[str, Any],
        task_graph: dict[str, Any],
        participants: list[dict[str, Any]],
        provided_inputs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Resume a runtime-registered tool approval using the same tool path.

        Registered-tool capabilities are executed by the auxiliary layer through
        RuntimeRegisteredToolService, not by a primary-runtime checkpoint.  When
        one pauses for human confirmation, the durable state needed for resume
        is the task-run parameter set plus the participant/tool binding.  This
        method rebuilds that invocation through the existing Agent/Task
        parameter contract and the RegisteredToolParameterBridge, then calls the
        same registered tool executor with approval_confirmed=true.
        """
        run_id = str(run_payload.get("run_id") or new_id("delegation_run"))
        task_name = str(task_graph.get("task_name") or run_payload.get("task_name") or "task")
        task_instruction = str(task_graph.get("instruction") or "")
        community_id = str(task_graph.get("community_id") or run_payload.get("community_id") or "default")
        runtime_parameters: dict[str, Any] = {}
        if isinstance(task_graph.get("runtime_parameters"), dict):
            runtime_parameters.update(task_graph.get("runtime_parameters") or {})
        if isinstance(run_payload.get("runtime_parameters"), dict):
            runtime_parameters.update(run_payload.get("runtime_parameters") or {})
        if isinstance(provided_inputs, dict):
            runtime_parameters.update({k: v for k, v in provided_inputs.items() if v not in (None, "", [], {})})
        pending = run_payload.get("pending_action") if isinstance(run_payload.get("pending_action"), dict) else {}
        tool_id = str(pending.get("tool_id") or "").strip()

        # The approval field may be participant-scoped by the UI.  Convert any
        # affirmative value into the generic runtime flag consumed by the
        # registered tool executor.  This keeps the old Agent/Task form system
        # intact while avoiding primary-runtime checkpoint resume for tool-only
        # approvals.
        if self._submitted_confirmation(runtime_parameters):
            runtime_parameters["approval_confirmed"] = True

        selected = self._fresh_task_participants(participants)
        selected = self._hydrate_runtime_bindings_for_task(task_graph, selected)
        self._apply_task_runtime_parameters_to_selected(selected, runtime_parameters)
        task_mind_graph = self._build_task_mind_graph(task_graph, selected)
        dependency_plan = task_mind_graph.get("agent_relation_analysis") or self._build_participant_dependency_plan(task_graph, selected)
        run_payload.update({
            "status": "resuming",
            "current_stage": "resuming_registered_tool_confirmation",
            "runtime_parameters": runtime_parameters,
            "participant_dependency_plan": dependency_plan,
            "task_mind_graph": task_mind_graph,
        })
        self._clear_waiting_fields(run_payload)
        self._record_progress(run_payload, "registered_tool_confirmation_resume", "Resuming registered tool confirmation", "running")

        agent_results: list[AgentExecutionResult] = []
        updated_payloads: list[dict[str, Any]] = []
        existing_by_participant = {
            str(item.get("participant_id") or ""): item
            for item in (run_payload.get("agent_results") or [])
            if isinstance(item, dict)
        }
        resumed_any = False
        for index, participant in enumerate(self._participants_in_mind_graph_order(selected, task_mind_graph)):
            pid = self._participant_identity(participant)
            profile = participant.get("capability_profile") if isinstance(participant.get("capability_profile"), dict) else {}
            participant_tool_id = str(profile.get("tool_id") or "").strip()
            existing = existing_by_participant.get(pid)
            should_resume = bool(participant_tool_id) and (not tool_id or participant_tool_id == tool_id)
            if not should_resume and isinstance(existing, dict):
                try:
                    restored = AgentExecutionResult(**existing)
                    agent_results.append(restored)
                    updated_payloads.append(self._sanitize_result_payload(restored.__dict__))
                except Exception:
                    updated_payloads.append(existing)
                continue
            if not should_resume:
                continue
            self._record_progress(run_payload, f"participant_{index + 1}_registered_tool_resume", f"Resuming registered tool participant: {self._participant_name(participant)}", "running")
            if self._submitted_confirmation(runtime_parameters) and self._submitted_trust_request(runtime_parameters):
                self._persist_approval_trust(participant=participant, tool_id=participant_tool_id)
            result = await self._execute_registered_tool_capability(participant=participant, task_name=task_name, completed_results=agent_results, dependency_plan=dependency_plan)
            if result is None:
                result = AgentExecutionResult(
                    participant_id=pid,
                    participant_name=self._participant_name(participant),
                    core_run_id=new_id("registered_tool_resume_failed"),
                    status="failed",
                    final_answer="Registered tool capability binding was not available during resume.",
                    workflow_results={"status": "failed", "reason": "registered_tool_binding_missing"},
                    origin="auxiliary_brain",
                )
            resumed_any = True
            agent_results.append(result)
            result_payload = self._sanitize_result_payload(result.__dict__)
            updated_payloads.append(result_payload)
            self._record_progress(run_payload, f"participant_{index + 1}_registered_tool_resume_complete", f"Registered tool participant resumed: {result.participant_name}", "completed" if result.status == "completed" else result.status)
            if result.status in {"requires_key", "requires_input", "paused"}:
                run_payload.update({
                    "status": result.status,
                    "current_stage": "waiting_for_required_input",
                    "pending_action": result.pending_action,
                    "missing_inputs": result.missing_inputs or [],
                    "agent_results": updated_payloads,
                    "completed_at": self._now(),
                })
                self._record_progress(run_payload, "waiting_input", "Waiting for required input", "waiting")
                self.store.write_json(f"generated/results/{run_id}.json", run_payload)
                return run_payload

        if not resumed_any:
            run_payload.update({
                "status": "failed",
                "current_stage": "failed",
                "message": "No registered tool participant matched the approval request.",
                "completed_at": self._now(),
            })
            self.store.write_json(f"generated/results/{run_id}.json", run_payload)
            return run_payload

        run_payload["agent_results"] = self._dedupe_result_payloads(updated_payloads)
        agent_results = self._to_agent_results(run_payload["agent_results"])
        synthesis_results = self._terminal_results_for_synthesis(agent_results, task_mind_graph)
        run_payload["synthesis_input_policy"] = {
            "mode": "terminal_graph_outputs",
            "source_result_count": len(agent_results),
            "synthesis_result_count": len(synthesis_results),
        }
        self._record_progress(run_payload, "final_synthesis", "Primary runtime synthesizing delegated results", "running")
        synthesis = await self.primary_client.synthesize_delegated_results(
            task_name=task_name,
            task_instruction=task_instruction,
            agent_results=synthesis_results,
            shared_context={"community_id": community_id, "task_mind_graph": task_mind_graph},
        )
        self._record_progress(run_payload, "final_synthesis_complete", "Final synthesis completed", "completed")
        delivery_id = new_id("delivery")
        delivery_payload = {
            "delivery_id": delivery_id,
            "origin": "auxiliary_brain",
            "upstream_origin": "ai_core",
            "task_name": task_name,
            "run_id": run_id,
            "final_answer": synthesis.get("final_answer"),
            "generated_files": self._collect_generated_files(agent_results),
            "synthesis": synthesis,
            "created_at": self._now(),
        }
        delivery_path = self.store.write_json(f"deliveries/{delivery_id}.json", delivery_payload)
        final_status = str(synthesis.get("status") or "")
        failed_statuses = {"failed", "completed_with_no_participant_result", "partial_failed", "no_usable_result"}
        run_payload.update({
            "status": "failed" if final_status in failed_statuses else "completed",
            "current_stage": "failed" if final_status in failed_statuses else "completed",
            "completed_at": self._now(),
            "synthesis": synthesis,
            "delivery": str(delivery_path),
        })
        self.store.write_json(f"generated/results/{run_id}.json", run_payload)
        return run_payload

    async def _resume_feedback_repair_confirmation(
        self,
        *,
        run_payload: dict[str, Any],
        task_graph: dict[str, Any],
        participants: list[dict[str, Any]],
        provided_inputs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Resume a paused feedback-repair proposal without primary checkpoints.

        Feedback repair for a runtime-registered capability is owned by the
        auxiliary layer.  The paused state must therefore be resumed from the
        saved delegation payload and participant/tool binding, not from a
        primary-runtime checkpoint.  This method rebuilds the original tool
        invocation, preserves the original user material for structural binding,
        and re-executes the failed registered-tool participant after the user
        confirms the repair path.
        """
        run_id = str(run_payload.get("run_id") or new_id("delegation_run"))
        task_name = str(task_graph.get("task_name") or run_payload.get("task_name") or "task")
        task_instruction = str(task_graph.get("instruction") or "")
        community_id = str(task_graph.get("community_id") or run_payload.get("community_id") or "default")
        pending = run_payload.get("pending_action") if isinstance(run_payload.get("pending_action"), dict) else {}

        runtime_parameters: dict[str, Any] = {}
        if isinstance(task_graph.get("runtime_parameters"), dict):
            runtime_parameters.update(task_graph.get("runtime_parameters") or {})
        if isinstance(run_payload.get("runtime_parameters"), dict):
            runtime_parameters.update(run_payload.get("runtime_parameters") or {})
        # Keep original task material available to schema-driven structural
        # binding.  This is generic source material, not a capability rule.
        source_material = "\n".join(
            str(x or "").strip()
            for x in (
                task_instruction,
                run_payload.get("instruction"),
                (run_payload.get("task_graph") or {}).get("instruction") if isinstance(run_payload.get("task_graph"), dict) else "",
                pending.get("original_user_material"),
            )
            if str(x or "").strip()
        )
        checkpoint = pending.get("resume_checkpoint") if isinstance(pending.get("resume_checkpoint"), dict) else {}
        checkpoint_material = str(checkpoint.get("original_user_material") or "").strip()
        if checkpoint_material:
            source_material = "\n".join(x for x in (source_material, checkpoint_material) if x)
        if source_material:
            runtime_parameters.setdefault("_original_user_material", source_material)
            structural_values = self._extract_structural_values_from_material(source_material)
            if structural_values:
                runtime_parameters.setdefault("_detected_structural_values", structural_values)
        checkpoint_structural = checkpoint.get("detected_structural_values") if isinstance(checkpoint.get("detected_structural_values"), dict) else {}
        if checkpoint_structural:
            runtime_parameters.setdefault("_detected_structural_values", checkpoint_structural)
        if isinstance(provided_inputs, dict):
            runtime_parameters.update({k: v for k, v in provided_inputs.items() if v not in (None, "", [], {})})

        if not self._submitted_confirmation(runtime_parameters):
            run_payload.update({
                "status": "paused",
                "current_stage": "repair_confirmation_required",
                "pending_action": pending,
                "runtime_parameters": runtime_parameters,
                "completed_at": self._now(),
                "message": "Repair confirmation is required before continuing.",
            })
            self.store.write_json(f"generated/results/{run_id}.json", run_payload)
            return run_payload

        tool_id = str(pending.get("tool_id") or "").strip()
        selected = self._fresh_task_participants(participants)
        selected = self._hydrate_runtime_bindings_for_task(task_graph, selected)
        self._apply_task_runtime_parameters_to_selected(selected, runtime_parameters)
        task_mind_graph = self._build_task_mind_graph(task_graph, selected)
        dependency_plan = task_mind_graph.get("agent_relation_analysis") or self._build_participant_dependency_plan(task_graph, selected)
        run_payload.update({
            "status": "resuming",
            "current_stage": "resuming_feedback_repair",
            "runtime_parameters": runtime_parameters,
            "participant_dependency_plan": dependency_plan,
            "task_mind_graph": task_mind_graph,
        })
        self._clear_waiting_fields(run_payload)
        self._record_progress(run_payload, "feedback_repair_resume", "Resuming confirmed feedback repair", "running")

        existing_payloads = [x for x in (run_payload.get("agent_results") or []) if isinstance(x, dict)]
        existing_by_participant = {str(item.get("participant_id") or ""): item for item in existing_payloads}
        agent_results: list[AgentExecutionResult] = []
        updated_payloads: list[dict[str, Any]] = []
        resumed_any = False

        for index, participant in enumerate(self._participants_in_mind_graph_order(selected, task_mind_graph)):
            pid = self._participant_identity(participant)
            profile = participant.get("capability_profile") if isinstance(participant.get("capability_profile"), dict) else {}
            participant_tool_id = str(profile.get("tool_id") or "").strip()
            existing = existing_by_participant.get(pid)
            should_resume = bool(participant_tool_id) and (not tool_id or participant_tool_id == tool_id)
            if not should_resume and isinstance(existing, dict):
                try:
                    restored = AgentExecutionResult(**existing)
                    agent_results.append(restored)
                    updated_payloads.append(self._sanitize_result_payload(restored.__dict__))
                except Exception:
                    updated_payloads.append(existing)
                continue
            if not should_resume:
                continue
            self._record_progress(run_payload, f"participant_{index + 1}_feedback_repair", f"Re-executing repaired participant: {self._participant_name(participant)}", "running")
            result = await self._execute_registered_tool_capability(participant=participant, task_name=task_name, completed_results=agent_results, dependency_plan=dependency_plan)
            if result is None:
                result = AgentExecutionResult(
                    participant_id=pid,
                    participant_name=self._participant_name(participant),
                    core_run_id=new_id("feedback_repair_resume_failed"),
                    status="failed",
                    final_answer="Registered capability binding was not available during repair resume.",
                    workflow_results={"status": "failed", "reason": "registered_capability_binding_missing"},
                    origin="auxiliary_brain",
                )
            resumed_any = True
            agent_results.append(result)
            result_payload = self._sanitize_result_payload(result.__dict__)
            updated_payloads.append(result_payload)
            self._record_progress(run_payload, f"participant_{index + 1}_feedback_repair_complete", f"Repaired participant finished: {result.participant_name}", "completed" if result.status == "completed" else result.status)
            if result.status in {"requires_key", "requires_input", "paused"}:
                run_payload.update({
                    "status": result.status,
                    "current_stage": "waiting_for_required_input",
                    "pending_action": result.pending_action,
                    "missing_inputs": result.missing_inputs or [],
                    "agent_results": updated_payloads,
                    "completed_at": self._now(),
                })
                self._record_progress(run_payload, "waiting_input", "Waiting for required input", "waiting")
                self.store.write_json(f"generated/results/{run_id}.json", run_payload)
                return run_payload

        if not resumed_any:
            run_payload.update({
                "status": "failed",
                "current_stage": "failed",
                "message": "No registered capability participant matched the repair request.",
                "completed_at": self._now(),
            })
            self.store.write_json(f"generated/results/{run_id}.json", run_payload)
            return run_payload

        run_payload["agent_results"] = self._dedupe_result_payloads(updated_payloads)
        agent_results = self._to_agent_results(run_payload["agent_results"])
        synthesis_results = self._terminal_results_for_synthesis(agent_results, task_mind_graph)
        run_payload["synthesis_input_policy"] = {
            "mode": "terminal_graph_outputs_after_feedback_repair",
            "source_result_count": len(agent_results),
            "synthesis_result_count": len(synthesis_results),
        }
        self._record_progress(run_payload, "final_synthesis", "Primary runtime synthesizing repaired delegated results", "running")
        synthesis = await self.primary_client.synthesize_delegated_results(
            task_name=task_name,
            task_instruction=task_instruction,
            agent_results=synthesis_results,
            shared_context={"community_id": community_id, "task_mind_graph": task_mind_graph},
        )
        self._record_progress(run_payload, "final_synthesis_complete", "Final synthesis completed after repair", "completed")
        delivery_id = new_id("delivery")
        delivery_payload = {
            "delivery_id": delivery_id,
            "origin": "auxiliary_brain",
            "upstream_origin": "ai_core",
            "task_name": task_name,
            "run_id": run_id,
            "final_answer": synthesis.get("final_answer"),
            "generated_files": self._collect_generated_files(agent_results),
            "synthesis": synthesis,
            "created_at": self._now(),
        }
        delivery_path = self.store.write_json(f"deliveries/{delivery_id}.json", delivery_payload)
        final_status = str(synthesis.get("status") or "")
        failed_statuses = {"failed", "completed_with_no_participant_result", "partial_failed", "no_usable_result"}
        run_payload.update({
            "status": "failed" if final_status in failed_statuses else "completed",
            "current_stage": "failed" if final_status in failed_statuses else "completed",
            "completed_at": self._now(),
            "synthesis": synthesis,
            "delivery": str(delivery_path),
        })
        self.store.write_json(f"generated/results/{run_id}.json", run_payload)
        return run_payload

    def _submitted_confirmation(self, values: dict[str, Any]) -> bool:
        if not isinstance(values, dict):
            return False
        for key, value in values.items():
            tail = str(key or "").split(".")[-1].split("_")[-1].casefold()
            if tail not in {"approval_confirmed", "confirmed", "confirm", "approved", "approval"}:
                continue
            if isinstance(value, bool):
                if value:
                    return True
                continue
            if isinstance(value, list):
                if any(self._submitted_confirmation({"approval_confirmed": item}) for item in value):
                    return True
                continue
            if str(value).strip().casefold() in {"true", "1", "yes", "y", "on", "confirmed", "approve", "approved"}:
                return True
        return False


    def _submitted_trust_request(self, values: dict[str, Any]) -> bool:
        if not isinstance(values, dict):
            return False
        accepted_tails = {
            "remember_approval",
            "remember_confirmation",
            "trust_after_confirmation",
            "skip_future_confirmation",
            "auto_confirm_future",
            "do_not_ask_again",
        }
        for key, value in values.items():
            tail = str(key or "").split(".")[-1].casefold()
            tail = tail.replace("-", "_")
            if tail not in accepted_tails:
                continue
            if isinstance(value, bool):
                if value:
                    return True
                continue
            if isinstance(value, list):
                if any(self._submitted_trust_request({"remember_approval": item}) for item in value):
                    return True
                continue
            if str(value).strip().casefold() in {"true", "1", "yes", "y", "on", "confirmed", "approve", "approved"}:
                return True
        return False

    def _approval_trusted(self, *, participant: dict[str, Any], tool_id: str, profile_id: str = "default") -> bool:
        """Return True when this run may execute without an approval pause.

        This method intentionally stays policy-driven.  It does not inspect
        agent names, task names, or capability-specific vocabulary.  It first
        respects the runtime tool/profile approval policy, then falls back to
        durable participant-tool trust created by an earlier explicit approval.
        """
        tool_id = str(tool_id or "").strip()
        if not tool_id:
            return False
        try:
            if self.registered_tool_service.approval_policy_store.is_auto_approved(tool_id=tool_id, profile_id=profile_id or "default"):
                return True
        except Exception:
            pass
        pid = self._participant_identity(participant)
        if not pid:
            return False
        record = self.store.read_json("configs/policies/approval_trust.json") or {}
        if not isinstance(record, dict):
            return False
        trusted = record.get("trusted") if isinstance(record.get("trusted"), dict) else {}
        entry = trusted.get(f"{pid}:{tool_id}") if isinstance(trusted, dict) else None
        return isinstance(entry, dict) and entry.get("enabled") is True

    def _is_approval_parameter_field(self, field: dict[str, Any]) -> bool:
        """Detect generic approval/confirmation parameter fields.

        This is a structural execution-policy field filter, not a domain rule.
        It keeps tool approval policy separate from ordinary task inputs.
        """
        if not isinstance(field, dict):
            return False
        names = [
            field.get("parameter_name"),
            field.get("name"),
            field.get("field"),
            field.get("key"),
        ]
        for item in names:
            tail = str(item or "").strip().rsplit(".", 1)[-1].replace("-", "_").casefold()
            if tail in {"approval_confirmed", "remember_approval", "confirm", "confirmed", "approval", "approved"}:
                return True
        role = str(field.get("input_role") or field.get("role") or "").strip().replace("-", "_").casefold()
        return role in {"approval", "confirmation", "execution_approval"}

    def _participant_tool_id(self, participant: dict[str, Any]) -> str:
        profile = participant.get("capability_profile") if isinstance(participant.get("capability_profile"), dict) else {}
        return str(profile.get("tool_id") or "").strip()

    def _persist_approval_trust(self, *, participant: dict[str, Any], tool_id: str) -> None:
        pid = self._participant_identity(participant)
        if not pid or not tool_id:
            return
        record = self.store.read_json("configs/policies/approval_trust.json") or {}
        if not isinstance(record, dict):
            record = {}
        trusted = record.setdefault("trusted", {})
        if not isinstance(trusted, dict):
            trusted = {}
            record["trusted"] = trusted
        trusted[f"{pid}:{tool_id}"] = {
            "enabled": True,
            "participant_id": pid,
            "participant_name": self._participant_name(participant),
            "tool_id": tool_id,
            "trusted_after_explicit_confirmation": True,
            "updated_at": self._now(),
        }
        self.store.write_json("configs/policies/approval_trust.json", record)

    def _is_public_dependency_material(self, value: Any) -> bool:
        text = str(value or "").strip()
        if not text:
            return False
        lowered = text.casefold()
        blocked_fragments = (
            "completed without a user-facing final answer",
            "intermediate node data was intentionally not exposed",
            "paused before producing a user-facing final answer",
            "no verified result material",
            "could not produce a verified answer",
            "workflow is blocked",
            "blocked step details",
            "generated workflow step did not produce",
            "required upstream results were unavailable",
        )
        if any(fragment in lowered for fragment in blocked_fragments):
            return False
        return any(ch.isalpha() or ch.isdigit() for ch in text)

    def _result_has_usable_material(self, result: Any) -> bool:
        """Return True when a result can safely feed downstream nodes.

        The availability decision must use the same public-output contract as
        variable binding.  Earlier versions scanned arbitrary nested stage
        values, so internal node labels could become downstream payload; later
        strict guards blocked those labels but also missed legitimate terminal
        answers stored under primary-runtime final nodes.  This method delegates
        to WorkflowOutputResolver so dependency gating and template binding see
        the same exportable material map.
        """
        if result is None:
            return False
        status = str(getattr(result, "status", "") or "").strip().lower()
        if status in {"requires_key", "requires_input", "paused", "timeout", "dependency_blocked"}:
            return False
        workflow_results = getattr(result, "workflow_results", None)
        if isinstance(workflow_results, dict):
            gate = workflow_results.get("dependency_gate")
            if isinstance(gate, dict) and str(gate.get("reason") or "") == "required_upstream_result_unavailable":
                return False
        fields = self.workflow_output_resolver.extract_public_fields(result)
        for value in fields.values():
            if self._is_public_dependency_material(value):
                return True
        return False

    def _dependency_result_is_available(self, result: Any) -> bool:
        if result is None:
            return False
        status = str(getattr(result, "status", "") or "").strip().lower()
        if status == "completed":
            return self._result_has_usable_material(result)
        return self._result_has_usable_material(result)

    def _blocked_dependency_ids(self, *, participant_id: str, completed_results: list[Any], dependency_plan: dict[str, Any]) -> list[str]:
        participants = dependency_plan.get("participants") if isinstance(dependency_plan, dict) else {}
        plan = participants.get(participant_id) if isinstance(participants, dict) else {}
        dependencies = [str(item).strip() for item in (plan.get("depends_on") if isinstance(plan, dict) else []) or [] if str(item).strip()]
        if not dependencies:
            return []
        result_by_id: dict[str, Any] = {}
        for result in completed_results:
            rid = str(getattr(result, "participant_id", "") or "").strip()
            rname = str(getattr(result, "participant_name", "") or "").strip()
            if rid:
                result_by_id[rid] = result
            if rname:
                result_by_id[rname] = result
        blocked: list[str] = []
        for dependency_id in dependencies:
            result = result_by_id.get(dependency_id)
            if result is None:
                blocked.append(dependency_id)
                continue
            if not self._dependency_result_is_available(result):
                blocked.append(dependency_id)
        return blocked

    def _dependency_blocked_result(self, *, participant_id: str, participant_name: str, blocked_by: list[str]) -> AgentExecutionResult:
        return AgentExecutionResult(
            participant_id=participant_id,
            participant_name=participant_name,
            core_run_id="dependency_blocked",
            status="failed",
            final_answer="This step was not executed because required upstream results were unavailable.",
            workflow_results={
                "dependency_gate": {
                    "status": "failed",
                    "blocked_by": blocked_by,
                    "reason": "required_upstream_result_unavailable",
                }
            },
            origin="auxiliary_brain",
        )

    async def reoptimize_result(
        self,
        *,
        run_payload: dict[str, Any],
        task_graph: dict[str, Any],
        feedback: dict[str, Any],
        strategy: dict[str, Any],
    ) -> dict[str, Any]:
        """Re-synthesize an existing run without restarting completed work."""
        run_id = str(run_payload.get("run_id") or new_id("delegation_run"))
        task_name = str(task_graph.get("task_name") or run_payload.get("task_name") or "task")
        task_instruction = str(task_graph.get("instruction") or "")
        community_id = str(task_graph.get("community_id") or run_payload.get("community_id") or "default")
        run_payload.setdefault("progress_events", [])
        run_payload["status"] = "reoptimizing"
        run_payload["current_stage"] = "adaptive_resynthesis"
        run_payload.setdefault("adaptation_events", []).append({
            "at": self._now(),
            "feedback": feedback,
            "strategy": strategy,
        })
        self._record_progress(run_payload, "adaptive_resynthesis", "Applying feedback and re-optimizing final result", "running")
        agent_results = self._to_agent_results(self._dedupe_result_payloads(run_payload.get("agent_results") or []))
        synthesis = await self.primary_client.synthesize_delegated_results(
            task_name=task_name,
            task_instruction=task_instruction,
            agent_results=agent_results,
            shared_context={
                "community_id": community_id,
                "feedback": feedback,
                "strategy": strategy,
                "model_escalation_requested": bool(strategy.get("model_escalation")),
            },
        )
        self._record_progress(run_payload, "adaptive_resynthesis_complete", "Adaptive final synthesis completed", "completed")
        delivery_id = new_id("delivery")
        delivery_payload = {
            "delivery_id": delivery_id,
            "origin": "auxiliary_brain",
            "upstream_origin": "ai_core",
            "task_name": task_name,
            "run_id": run_id,
            "final_answer": synthesis.get("final_answer"),
            "generated_files": self._collect_generated_files(agent_results),
            "synthesis": synthesis,
            "adaptation": {"feedback": feedback, "strategy": strategy},
            "created_at": self._now(),
        }
        delivery_path = self.store.write_json(f"deliveries/{delivery_id}.json", delivery_payload)
        final_status = str(synthesis.get("status") or "")
        failed_statuses = {"failed", "completed_with_no_participant_result", "partial_failed", "no_usable_result"}
        run_payload.update({
            "status": "failed" if final_status in failed_statuses else "completed",
            "current_stage": "failed" if final_status in failed_statuses else "completed",
            "completed_at": self._now(),
            "synthesis": synthesis,
            "delivery": str(delivery_path),
        })
        self.store.write_json(f"generated/results/{run_id}.json", run_payload)
        return run_payload


    async def resume_task(self, run_payload: dict[str, Any], task_graph: dict[str, Any], participants: list[dict[str, Any]], provided_inputs: dict[str, Any] | None = None) -> dict[str, Any]:
        """Resume the same delegation run from its paused participant checkpoint.

        This method must not create a new run id and must not restart already
        completed participant work. It resumes the participant result that owns
        the saved primary-runtime checkpoint, then continues the remaining
        participants and final synthesis.
        """
        run_id = str(run_payload.get("run_id") or "").strip()
        if not run_id:
            run_payload["status"] = "failed"
            run_payload["message"] = "Run id is required for durable resume."
            return run_payload

        task_name = str(task_graph.get("task_name") or run_payload.get("task_name") or "task")
        task_instruction = str(task_graph.get("instruction") or "")
        community_id = str(task_graph.get("community_id") or run_payload.get("community_id") or "default")
        selected = self._fresh_task_participants(self._select_participants(task_graph, participants))
        selected = self._hydrate_runtime_bindings_for_task(task_graph, selected)

        # Resume must use the same task-run parameter map that was parsed when
        # the task graph was created.  Previous code only applied these values
        # on a brand-new run.  After a participant pause, the continuation path
        # rebuilt fresh participant copies and then executed the remaining
        # participants without re-applying run-scoped parameters.  That made
        # downstream registered tools ask again for values that were already in
        # the durable task graph.  Merge task, run, and newly provided values
        # once here, then apply them to every in-memory participant copy.
        runtime_parameters = {}
        if isinstance(task_graph.get("runtime_parameters"), dict):
            runtime_parameters.update(task_graph.get("runtime_parameters") or {})
        if isinstance(run_payload.get("runtime_parameters"), dict):
            runtime_parameters.update(run_payload.get("runtime_parameters") or {})
        if isinstance(provided_inputs, dict):
            runtime_parameters.update({k: v for k, v in provided_inputs.items() if v not in (None, "", [], {})})
        if runtime_parameters:
            task_graph = dict(task_graph)
            task_graph["runtime_parameters"] = runtime_parameters
            run_payload["runtime_parameters"] = runtime_parameters
            self._apply_task_runtime_parameters_to_selected(selected, runtime_parameters)

        pending = run_payload.get("pending_action") if isinstance(run_payload.get("pending_action"), dict) else {}
        if str(pending.get("kind") or "") == "agent_parameter_collection" and not run_payload.get("agent_results"):
            # Top-level agent parameter collection before any participant has
            # executed may safely start a fresh task run with the completed
            # runtime parameter map.  If agent_results already exist, this is a
            # participant-level pause and must be resumed below without
            # re-running completed upstream participants.
            selected = self._fresh_task_participants(selected)
            runtime_parameters = {}
            if isinstance(task_graph.get("runtime_parameters"), dict):
                runtime_parameters.update(task_graph.get("runtime_parameters") or {})
            if isinstance(run_payload.get("runtime_parameters"), dict):
                runtime_parameters.update(run_payload.get("runtime_parameters") or {})
            if isinstance(provided_inputs, dict):
                runtime_parameters.update({k: v for k, v in provided_inputs.items() if v not in (None, "", [], {})})
            self._apply_task_runtime_parameters_to_selected(selected, runtime_parameters)
            task_graph = dict(task_graph)
            task_graph["runtime_parameters"] = runtime_parameters
            return await self._execute_task_with_selected(task_graph, selected)
        if str(pending.get("kind") or "") == "runtime_tool_human_confirmation":
            return await self._resume_registered_tool_confirmation(
                run_payload=run_payload,
                task_graph=task_graph,
                participants=selected,
                provided_inputs=provided_inputs,
            )
        if str(pending.get("kind") or "") == "feedback_repair_confirmation":
            return await self._resume_feedback_repair_confirmation(
                run_payload=run_payload,
                task_graph=task_graph,
                participants=selected,
                provided_inputs=provided_inputs,
            )
        if str(pending.get("kind") or "") == "runtime_input_update_required":
            selected = self._fresh_task_participants(selected)
            runtime_parameters = {}
            if isinstance(task_graph.get("runtime_parameters"), dict):
                runtime_parameters.update(task_graph.get("runtime_parameters") or {})
            if isinstance(run_payload.get("runtime_parameters"), dict):
                runtime_parameters.update(run_payload.get("runtime_parameters") or {})
            checkpoint = pending.get("resume_checkpoint") if isinstance(pending.get("resume_checkpoint"), dict) else {}
            if checkpoint.get("original_user_material"):
                runtime_parameters.setdefault("_original_user_material", checkpoint.get("original_user_material"))
            if isinstance(checkpoint.get("detected_structural_values"), dict):
                runtime_parameters.setdefault("_detected_structural_values", checkpoint.get("detected_structural_values"))
            if isinstance(provided_inputs, dict):
                runtime_parameters.update({k: v for k, v in provided_inputs.items() if v not in (None, "", [], {})})
            self._apply_task_runtime_parameters_to_selected(selected, runtime_parameters)
            task_graph = dict(task_graph)
            task_graph["runtime_parameters"] = runtime_parameters
            return await self._execute_task_with_selected(task_graph, selected)
        if str(pending.get("kind") or "") in {"profile_secret_update_required", "profile_configuration_update_required"}:
            run_payload.update({
                "status": "paused",
                "current_stage": str(pending.get("kind") or "profile_update_required"),
                "message": str((pending.get("request") or {}).get("message") or pending.get("message") or "Update the selected profile and retry the task."),
                "pending_action": pending,
                "completed_at": self._now(),
            })
            self.store.write_json(f"generated/results/{run_id}.json", run_payload)
            return run_payload
        task_mind_graph = self._build_task_mind_graph(task_graph, selected)
        dependency_plan = task_mind_graph.get("agent_relation_analysis") or self._build_participant_dependency_plan(task_graph, selected)
        run_payload["participant_dependency_plan"] = dependency_plan
        run_payload["status"] = "resuming"
        run_payload["current_stage"] = "resuming"
        # Once resume has been accepted, the top-level waiting contract must be
        # cleared immediately. Otherwise the UI keeps showing a required-input
        # prompt while the primary runtime is already continuing from the
        # checkpoint. Participant-level paused payloads are left intact until
        # the primary runtime returns the resumed result, because they carry the
        # durable checkpoint identity needed by the resume call.
        self._clear_waiting_fields(run_payload)
        self._record_progress(run_payload, "durable_resume", "Durable resume requested", "running")
        self.store.write_json(f"generated/results/{run_id}.json", run_payload)

        existing_results = self._dedupe_result_payloads(list(run_payload.get("agent_results") or []))
        resumed_index = None
        agent_results = []
        for idx, payload in enumerate(existing_results):
            status = str(payload.get("status") or "")
            if resumed_index is None and status in {"requires_key", "requires_input", "paused"}:
                resumed_index = idx
                self._record_progress(run_payload, f"participant_{idx + 1}_resume", f"Resuming participant from checkpoint: {payload.get('participant_name') or 'participant'}", "running")
                resumed = await self._resume_agent_request_with_progress(
                    payload,
                    self._build_primary_runtime_progress_bridge(
                        run_payload,
                        participant_index=idx + 1,
                        participant_name=str(payload.get("participant_name") or "participant"),
                        resume=True,
                    ),
                    provided_inputs=provided_inputs,
                )
                resumed_payload = self._sanitize_result_payload(resumed.__dict__)
                existing_results[idx] = resumed_payload
                existing_results = self._dedupe_result_payloads(existing_results)
                run_payload["agent_results"] = existing_results
                if resumed.status not in {"requires_key", "requires_input", "paused"}:
                    self._clear_waiting_fields(run_payload)
                agent_results.append(resumed)
                self._record_progress(run_payload, f"participant_{idx + 1}_resume_complete", f"Participant resumed: {resumed.participant_name}", "completed" if resumed.status == "completed" else resumed.status)
                if resumed.status in {"requires_key", "requires_input", "paused"}:
                    run_payload.update({
                        "status": resumed.status,
                        "current_stage": "waiting_for_required_input",
                        "pending_action": resumed.pending_action,
                        "missing_inputs": resumed.missing_inputs or [],
                    })
                    run_payload["agent_results"] = existing_results
                    self._record_progress(run_payload, "waiting_input", "Waiting for required input", "waiting")
                    self.store.write_json(f"generated/results/{run_id}.json", run_payload)
                    return run_payload
            else:
                # Preserve completed results without re-running them.
                try:
                    from ai_core.agent_delegation import AgentExecutionResult
                    agent_results.append(AgentExecutionResult(**payload))
                except Exception:
                    pass

        if resumed_index is None:
            run_payload["status"] = "failed"
            run_payload["message"] = "No paused participant checkpoint was found for durable resume."
            self.store.write_json(f"generated/results/{run_id}.json", run_payload)
            return run_payload

        # Continue any selected participants that have not produced a result yet.
        completed_ids = {str(r.get("participant_id") or "") for r in existing_results}
        for index, participant in enumerate(selected):
            participant_id = str(participant.get("participant_id") or participant.get("id") or "")
            if participant_id in completed_ids:
                continue
            participant_name = str(participant.get("display_name") or participant.get("agent_name") or participant.get("name") or participant_id or "participant")
            self._record_progress(run_payload, f"participant_{index + 1}_primary_runtime", f"Primary runtime executing participant: {participant_name}", "running")
            self._bind_dependency_outputs_to_participant(
                participant=participant,
                completed_results=agent_results,
                dependency_plan=dependency_plan,
            )
            capability_result = await self._try_execute_generated_capability(
                participant=participant,
                completed_results=agent_results,
                dependency_plan=dependency_plan,
                task_name=task_name,
            )
            if capability_result is not None:
                result = capability_result
                result_payload = self._sanitize_result_payload(result.__dict__)
                agent_results.append(result)
                run_payload["agent_results"].append(result_payload)
                self._record_progress(
                    run_payload,
                    f"participant_{index + 1}_complete",
                    f"Participant finished: {participant_name}",
                    "completed" if result.status == "completed" else result.status,
                )
                if result.status in {"requires_key", "requires_input", "paused"}:
                    run_payload.update({
                        "status": result.status,
                        "current_stage": "waiting_for_required_input",
                        "pending_action": result.pending_action,
                        "missing_inputs": result.missing_inputs or [],
                        "completed_at": self._now(),
                    })
                    self._record_progress(run_payload, "waiting_input", "Waiting for required input", "waiting")
                    self.store.write_json(f"generated/results/{run_id}.json", run_payload)
                    return run_payload
                continue
            request = AgentExecutionRequest(
                participant_id=participant_id,
                participant_name=participant_name,
                participant_instruction=str(participant.get("execution_objective") or participant.get("instruction") or participant.get("description") or ""),
                task_name=task_name,
                task_instruction=task_instruction,
                community_id=community_id,
                shared_context=self._build_participant_shared_context(
                    task_graph=task_graph,
                    selected=selected,
                    participant=participant,
                    completed_results=agent_results,
                    dependency_plan=dependency_plan,
                    task_mind_graph=task_mind_graph,
                    for_input_parsing=True,
                ),
            )
            result = await self._execute_workflow_step_through_ai_core_with_progress(
                request,
                self._build_primary_runtime_progress_bridge(
                    run_payload,
                    participant_index=index + 1,
                    participant_name=participant_name,
                ),
            )
            payload = self._sanitize_result_payload(result.__dict__)
            existing_results.append(payload)
            agent_results.append(result)
            self._record_progress(run_payload, f"participant_{index + 1}_complete", f"Participant finished: {participant_name}", "completed" if result.status == "completed" else result.status)
            if result.status in {"requires_key", "requires_input", "paused"}:
                run_payload.update({
                    "status": result.status,
                    "current_stage": "waiting_for_required_input",
                    "pending_action": result.pending_action,
                    "missing_inputs": result.missing_inputs or [],
                })
                run_payload["agent_results"] = existing_results
                self._record_progress(run_payload, "waiting_input", "Waiting for required input", "waiting")
                self.store.write_json(f"generated/results/{run_id}.json", run_payload)
                return run_payload
            continue
            capability_result = await self._try_execute_generated_capability(
                participant=participant,
                completed_results=agent_results,
                dependency_plan=dependency_plan,
                task_name=task_name,
            )
            if capability_result is not None:
                payload = self._sanitize_result_payload(capability_result.__dict__)
                existing_results.append(payload)
                agent_results.append(capability_result)
                self._record_progress(run_payload, f"participant_{index + 1}_complete", f"Participant finished: {participant_name}", "completed" if capability_result.status == "completed" else capability_result.status)
                if capability_result.status in {"requires_key", "requires_input", "paused"}:
                    run_payload.update({
                        "status": capability_result.status,
                        "current_stage": "waiting_for_required_input",
                        "pending_action": capability_result.pending_action,
                        "missing_inputs": capability_result.missing_inputs or [],
                    })
                    run_payload["agent_results"] = existing_results
                    self._record_progress(run_payload, "waiting_input", "Waiting for required input", "waiting")
                    self.store.write_json(f"generated/results/{run_id}.json", run_payload)
                    return run_payload
                continue
            material_result = self._try_execute_file_material_generation(
                participant=participant,
                completed_results=agent_results,
                dependency_plan=dependency_plan,
                task_name=task_name,
            )
            if material_result is not None:
                payload = self._sanitize_result_payload(material_result.__dict__)
                existing_results.append(payload)
                agent_results.append(material_result)
                self._record_progress(run_payload, f"participant_{index + 1}_complete", f"Participant finished: {participant_name}", "completed")
                continue
            request = AgentExecutionRequest(
                participant_id=participant_id,
                participant_name=participant_name,
                participant_instruction=str(participant.get("execution_objective") or participant.get("instruction") or participant.get("description") or ""),
                task_name=task_name,
                task_instruction=task_instruction,
                community_id=community_id,
                shared_context=self._build_participant_shared_context(
                    task_graph=task_graph,
                    selected=selected,
                    participant=participant,
                    completed_results=agent_results,
                    dependency_plan=dependency_plan,
                    task_mind_graph=task_mind_graph,
                    for_input_parsing=True,
                ),
            )
            if self._is_generated_dataflow_step(participant, task_graph):
                material_return = self._try_return_dependency_material(
                    participant=participant,
                    completed_results=agent_results,
                    dependency_plan=dependency_plan,
                )
                if material_return is not None:
                    result = material_return
                else:
                    result = await self._execute_intermediate_step_with_progress(
                        request,
                        self._build_primary_runtime_progress_bridge(
                            run_payload,
                            participant_index=index + 1,
                            participant_name=participant_name,
                        ),
                    )
            else:
                result = await self._execute_agent_request_with_progress(
                    request,
                    self._build_primary_runtime_progress_bridge(
                        run_payload,
                        participant_index=index + 1,
                        participant_name=participant_name,
                    ),
                )
            payload = self._sanitize_result_payload(result.__dict__)
            existing_results.append(payload)
            agent_results.append(result)
            self._record_progress(run_payload, f"participant_{index + 1}_complete", f"Participant finished: {participant_name}", "completed" if result.status == "completed" else result.status)
            if result.status in {"failed", "incomplete", "timeout"}:
                # Do not mark a failed primary-runtime participant as successful.
                # Keep executing remaining participants so the final synthesis can
                # report all failures, but preserve the failure status in payload.
                pass
            if result.status in {"requires_key", "requires_input", "paused"}:
                run_payload.update({
                    "status": result.status,
                    "current_stage": "waiting_for_required_input",
                    "pending_action": result.pending_action,
                    "missing_inputs": result.missing_inputs or [],
                })
                run_payload["agent_results"] = existing_results
                self._record_progress(run_payload, "waiting_input", "Waiting for required input", "waiting")
                self.store.write_json(f"generated/results/{run_id}.json", run_payload)
                return run_payload

        existing_results = self._dedupe_result_payloads(existing_results)
        run_payload["agent_results"] = existing_results
        self._clear_waiting_fields(run_payload)
        agent_results = self._to_agent_results(existing_results)
        synthesis_results = self._terminal_results_for_synthesis(agent_results, task_mind_graph)
        run_payload["synthesis_input_policy"] = {
            "mode": "terminal_graph_outputs",
            "source_result_count": len(agent_results),
            "synthesis_result_count": len(synthesis_results),
        }
        self._record_progress(run_payload, "final_synthesis", "Primary runtime synthesizing delegated results", "running")
        synthesis = await self.primary_client.synthesize_delegated_results(
            task_name=task_name,
            task_instruction=task_instruction,
            agent_results=synthesis_results,
            shared_context={"community_id": community_id, "task_mind_graph": task_mind_graph},
        )
        self._record_progress(run_payload, "final_synthesis_complete", "Final synthesis completed", "completed")
        delivery_id = new_id("delivery")
        delivery_payload = {
            "delivery_id": delivery_id,
            "origin": "auxiliary_brain",
            "upstream_origin": "ai_core",
            "task_name": task_name,
            "run_id": run_id,
            "final_answer": synthesis.get("final_answer"),
            "generated_files": self._collect_generated_files(agent_results),
            "synthesis": synthesis,
            "created_at": self._now(),
        }
        delivery_path = self.store.write_json(f"deliveries/{delivery_id}.json", delivery_payload)
        final_status = str(synthesis.get("status") or "")
        failed_statuses = {"failed", "completed_with_no_participant_result", "partial_failed", "no_usable_result"}
        run_payload.update({
            "status": "failed" if final_status in failed_statuses else "completed",
            "current_stage": "failed" if final_status in failed_statuses else "completed",
            "completed_at": self._now(),
            "synthesis": synthesis,
            "delivery": str(delivery_path),
        })
        self.store.write_json(f"generated/results/{run_id}.json", run_payload)
        return run_payload



    def _collect_generated_files(self, agent_results: list[Any]) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        seen: set[str] = set()
        for result in agent_results or []:
            for item in self._generated_files_from_result(result):
                key = str(item.get("download_url") or item.get("file_path") or item.get("file_name") or "")
                if key and key in seen:
                    continue
                if key:
                    seen.add(key)
                files.append(item)
        return files

    def _participant_identity(self, participant: dict[str, Any]) -> str:
        return str(participant.get("participant_id") or participant.get("id") or participant.get("name") or "").strip()

    def _participant_name(self, participant: dict[str, Any]) -> str:
        return str(participant.get("display_name") or participant.get("participant_display_name") or participant.get("agent_name") or participant.get("name") or participant.get("participant_id") or participant.get("id") or "participant").strip()

    def _participant_objective(self, participant: dict[str, Any]) -> str:
        return str(participant.get("execution_objective") or participant.get("instruction") or participant.get("description") or "").strip()

    def _build_task_mind_graph(self, task_graph: dict[str, Any], selected: list[dict[str, Any]]) -> dict[str, Any]:
        """Create the top-level task mind graph before executing agents.

        The graph is stored in runtime results and used only for coordination.
        Every agent still runs its own primary-runtime flow. Independent agent
        nodes do not receive peer output. Dependent agent nodes receive only the
        upstream safe JSON summaries declared by graph edges.
        """
        return TaskMindGraphBuilder().build(task_graph, selected)

    def _record_global_mind_graph_progress(self, run_payload: dict[str, Any], task_mind_graph: dict[str, Any]) -> None:
        stages = [
            ("global_input_parsing", "Global task input parsing completed"),
            ("global_intent_recognition", "Global task intent recognition completed"),
            ("global_workflow_planning", "Global task workflow planning completed"),
            ("global_agent_relation_analysis", "Agent relation analysis completed"),
            ("global_graph_generation", "Task mind graph generated"),
        ]
        for stage, label in stages:
            self._record_progress(run_payload, stage, label, "completed")
        run_payload["current_stage"] = "task_mind_graph_generated"

    def _participants_in_mind_graph_order(self, selected: list[dict[str, Any]], task_mind_graph: dict[str, Any]) -> list[dict[str, Any]]:
        by_id = {self._participant_identity(p): p for p in selected if self._participant_identity(p)}
        ordered: list[dict[str, Any]] = []
        for group in ((task_mind_graph.get("execution_plan") or {}).get("groups") or []):
            for pid in group:
                participant = by_id.get(str(pid))
                if participant and participant not in ordered:
                    ordered.append(participant)
        for participant in selected:
            if participant not in ordered:
                ordered.append(participant)
        return ordered

    def _mind_graph_node_for_participant(self, task_mind_graph: dict[str, Any], participant: dict[str, Any]) -> dict[str, Any]:
        pid = self._participant_identity(participant)
        for node in task_mind_graph.get("nodes") or []:
            if isinstance(node, dict) and str(node.get("node_id") or "") == pid:
                return node
        return {}

    def _build_participant_dependency_plan(self, task_graph: dict[str, Any], selected: list[dict[str, Any]]) -> dict[str, Any]:
        """Build a coordination-only dependency plan for participant execution.

        Default is independent. A participant receives another participant's
        result only when there is an explicit dependency signal in the task
        graph/participant definition or a clear textual reference to that
        participant's result. This prevents unrelated agents from polluting each
        other's LLM input-parsing prompts.
        """
        identities = {self._participant_identity(p): p for p in selected if self._participant_identity(p)}
        name_to_id = {self._participant_name(p).lower(): pid for pid, p in identities.items()}
        # Build a generic alias map for compiled/decomposed step identifiers.
        # Dependencies may be declared as step_001, step_1, Step 1, task ids,
        # participant ids, or participant names.  Runtime dependency checks must
        # resolve all of them to executable participant ids before execution.
        dependency_alias_to_pid: dict[str, str] = {}

        def _alias(value: Any) -> str:
            return self.workflow_output_resolver.normalize_key(value)

        def _add_alias(value: Any, pid_value: str) -> None:
            key = _alias(value)
            if key and pid_value:
                dependency_alias_to_pid.setdefault(key, pid_value)

        for participant_pid, participant in identities.items():
            _add_alias(participant_pid, participant_pid)
            _add_alias(self._participant_name(participant), participant_pid)
            _add_alias(participant.get("source_step_id"), participant_pid)
            _add_alias(participant.get("declared_step_id"), participant_pid)
            _add_alias(participant.get("structural_step_id"), participant_pid)

        for ordinal, task in enumerate(task_graph.get("tasks") or [], start=1):
            if not isinstance(task, dict):
                continue
            task_pid = str(task.get("participant_id") or task.get("participant") or task.get("agent_id") or "").strip()
            if not task_pid:
                continue
            aliases = [
                task_pid,
                task.get("id"),
                task.get("task_id"),
                task.get("step_id"),
                task.get("source_step_id"),
                task.get("declared_step_id"),
                task.get("structural_step_id"),
                task.get("participant_display_name"),
                task.get("display_name"),
                task.get("name"),
                f"step{ordinal}",
                f"step_{ordinal}",
                f"step {ordinal}",
                f"stage{ordinal}",
                f"stage_{ordinal}",
                f"stage {ordinal}",
            ]
            for value in aliases:
                _add_alias(value, task_pid)
            # Also normalize numeric forms embedded in a step id.  This keeps
            # step_1, step_001, Step 1 and generated_step_1 interchangeable.
            for value in aliases:
                match = re.search(r"(\d+)", str(value or ""))
                if match:
                    number = int(match.group(1))
                    _add_alias(f"step{number}", task_pid)
                    _add_alias(f"step_{number}", task_pid)
                    _add_alias(f"step {number}", task_pid)
                    _add_alias(f"step_{number:03d}", task_pid)
                    _add_alias(f"stage{number}", task_pid)
                    _add_alias(f"stage_{number}", task_pid)

        plan: dict[str, Any] = {
            "default_relationship": "independent",
            "participants": {},
            "edges": [],
        }
        explicit_by_task: dict[str, list[str]] = {}
        for task in task_graph.get("tasks") or []:
            if not isinstance(task, dict):
                continue
            target = str(task.get("participant_id") or task.get("participant") or task.get("agent_id") or "").strip()
            raw_deps = task.get("depends_on") or task.get("requires") or task.get("input_from") or []
            if isinstance(raw_deps, dict):
                raw_deps = [raw_deps]
            if isinstance(raw_deps, str):
                raw_deps = [raw_deps]
            deps: list[str] = []
            for item in raw_deps:
                raw = item.get("id") if isinstance(item, dict) else item
                dep = str(raw or "").strip()
                if dep:
                    deps.append(dep)
            if target and deps:
                explicit_by_task.setdefault(target, []).extend(deps)

        for pid, participant in identities.items():
            objective = self._participant_objective(participant).lower()
            raw_deps = participant.get("depends_on") or participant.get("requires") or participant.get("input_from") or explicit_by_task.get(pid) or []
            if isinstance(raw_deps, dict):
                raw_deps = [raw_deps]
            if isinstance(raw_deps, str):
                raw_deps = [raw_deps]
            deps: list[str] = []
            for item in raw_deps:
                raw = item.get("id") if isinstance(item, dict) else item
                dep = str(raw or "").strip()
                if not dep:
                    continue
                dep_id = dependency_alias_to_pid.get(_alias(dep)) or (dep if dep in identities else name_to_id.get(dep.lower(), dep))
                if dep_id != pid and dep_id in identities and dep_id not in deps:
                    deps.append(dep_id)
            # Dependencies must come from the task graph or participant metadata.
            # Source code must not infer semantic dataflow from vocabulary lists.
            relationship = "dependent" if deps else "independent"
            plan["participants"][pid] = {
                "participant_id": pid,
                "participant_name": self._participant_name(participant),
                "relationship": relationship,
                "depends_on": deps,
                "peer_results_injected": bool(deps),
            }
            for dep_id in deps:
                plan["edges"].append({"from": dep_id, "to": pid, "reason": "declared_or_clear_result_reference"})
        return plan


    def _step_source_contract(self, participant: dict[str, Any]) -> dict[str, Any]:
        """Return a structural source-material contract for one decomposed step.

        This is syntax/contract based and domain-neutral.  It does not inspect
        the task topic.  When a step explicitly asks for provenance-like output
        fields, the primary runtime should obtain source material instead of
        treating the step as a pure prompt or a missing-information request.
        """
        fragment = str(participant.get("source_instruction_fragment") or participant.get("execution_objective") or participant.get("instruction") or "")
        requested_fields: list[str] = []
        for raw in fragment.splitlines():
            line = raw.strip()
            if not line.startswith(("-", "*")):
                continue
            field = line.lstrip("-* ").strip().strip(":：").casefold()
            if field:
                requested_fields.append(field)
        normalized = {re.sub(r"[^a-z0-9]+", "_", item).strip("_") for item in requested_fields}
        provenance_fields = {
            "source", "sources", "reference", "references", "citation", "citations",
            "url", "link", "links", "published_at", "publication_time", "time", "date",
        }
        requires_source_material = bool(normalized & provenance_fields)
        return {
            "contract_type": "step_source_material_contract",
            "requires_source_material": requires_source_material,
            "requested_output_fields": requested_fields,
            "reason": "requested_output_provenance_fields" if requires_source_material else "not_declared",
        }

    def _build_participant_shared_context(
        self,
        *,
        task_graph: dict[str, Any],
        selected: list[dict[str, Any]],
        participant: dict[str, Any],
        completed_results: list[Any],
        dependency_plan: dict[str, Any],
        task_mind_graph: dict[str, Any] | None = None,
        for_input_parsing: bool = False,
    ) -> dict[str, Any]:
        task_mind_graph = task_mind_graph or self._build_task_mind_graph(task_graph, selected)
        participant_id = self._participant_identity(participant)
        participant_plan = (dependency_plan.get("participants") or {}).get(participant_id) or {}
        own_node = self._mind_graph_node_for_participant(task_mind_graph, participant)
        # For the participant's first input_parsing call, pass only its own
        # minimal parameter state. Do not include the full mind graph, dependency
        # plan, policy blocks, or peer results. Those coordination artifacts stay
        # in the delegation run and are used by final synthesis / dependent-agent
        # later stages only.
        if for_input_parsing:
            input_context = {
                "task_graph_id": task_graph.get("graph_id"),
                "participant_count": len(selected),
                "relationship": participant_plan.get("relationship") or own_node.get("relation") or "independent",
                "depends_on": participant_plan.get("depends_on") or own_node.get("depends_on") or [],
                "workflow_step_type": self._participant_workflow_step_type(participant, task_graph),
                "source_step_id": participant.get("source_step_id") or own_node.get("source_step_id"),
                "agent_parameters": {
                    "values": self._merged_runtime_parameters(task_graph, participant),
                    "missing": [] if self._uses_uploaded_artifact_runtime_for_task(participant, task_graph) else self.parameter_contract_service.missing_parameters(participant),
                },
                "uploaded_artifacts": participant.get("uploaded_artifacts") or task_graph.get("uploaded_artifacts") or [],
                "available_artifacts": participant.get("uploaded_artifacts") or task_graph.get("uploaded_artifacts") or [],
                "artifact_policy": participant.get("artifact_policy") or {},
                "artifact_binding": {
                    "available": bool(participant.get("uploaded_artifacts") or task_graph.get("uploaded_artifacts")),
                    "resolution_key": "artifact_id_or_filename",
                    "preferred_action_type": "use_uploaded_file",
                },
                "source_contract": self._step_source_contract(participant),
            }
            peer_results = self._peer_results_for_participant(participant, completed_results, dependency_plan)
            if peer_results:
                input_context["available_peer_results"] = peer_results
            return input_context

        shared_context: dict[str, Any] = {
            "task_graph_id": task_graph.get("graph_id"),
            "participant_count": len(selected),
            "relationship": participant_plan.get("relationship") or own_node.get("relation") or "independent",
            "depends_on": participant_plan.get("depends_on") or own_node.get("depends_on") or [],
            "workflow_step_type": self._participant_workflow_step_type(participant, task_graph),
            "source_step_id": participant.get("source_step_id") or own_node.get("source_step_id"),
            "participant_dependency_policy": {
                "default_relationship": "independent",
                "peer_results_are_injected_only_for_declared_dependencies": True,
                "independent_results_are_merged_only_at_final_synthesis": True,
                "peer_result_format": "strict_json_safe_summary",
            },
            "agent_parameters": {
                "values": self._merged_runtime_parameters(task_graph, participant),
                "contract": {} if self._uses_uploaded_artifact_runtime_for_task(participant, task_graph) else self._compact_parameter_contract(participant.get("parameter_contract") or {}),
            },
            "uploaded_artifacts": participant.get("uploaded_artifacts") or task_graph.get("uploaded_artifacts") or [],
            "available_artifacts": participant.get("uploaded_artifacts") or task_graph.get("uploaded_artifacts") or [],
            "artifact_policy": participant.get("artifact_policy") or {},
            "artifact_binding": {
                "available": bool(participant.get("uploaded_artifacts") or task_graph.get("uploaded_artifacts")),
                "resolution_key": "artifact_id_or_filename",
                "preferred_action_type": "use_uploaded_file",
            },
        }
        peer_results = self._peer_results_for_participant(participant, completed_results, dependency_plan)
        if peer_results:
            shared_context["available_peer_results"] = peer_results
        return shared_context




    def _terminal_results_for_synthesis(self, agent_results: list[Any], task_mind_graph: dict[str, Any]) -> list[Any]:
        """Return only terminal graph outputs for final answer synthesis.

        In a dataflow graph, upstream participant outputs are inputs to a later
        node, not final answers.  The final synthesis should consume terminal
        nodes so post-processing steps are not bypassed.  For independent graphs
        with no participant-to-participant edges, every participant remains a
        terminal output.
        """
        if not isinstance(task_mind_graph, dict) or not agent_results:
            return agent_results
        result_ids = {str(getattr(result, "participant_id", "") or "") for result in agent_results}
        outgoing: set[str] = set()
        for edge in task_mind_graph.get("edges") or []:
            if not isinstance(edge, dict):
                continue
            src = str(edge.get("from") or "").strip()
            dst = str(edge.get("to") or "").strip()
            if src in result_ids and dst in result_ids:
                outgoing.add(src)
        terminal = [result for result in agent_results if str(getattr(result, "participant_id", "") or "") not in outgoing]
        return terminal or agent_results

    def _parameter_alias_token(self, value: Any) -> str:
        return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().casefold()).strip("_")

    def _participant_parameter_aliases(self, participant: dict[str, Any]) -> set[str]:
        aliases: set[str] = set()
        for value in (
            self._participant_identity(participant),
            self._participant_name(participant),
            participant.get("agent_name"),
            participant.get("display_name"),
            participant.get("participant_display_name"),
            participant.get("name"),
            participant.get("id"),
            participant.get("participant_id"),
        ):
            raw = str(value or "").strip()
            if not raw:
                continue
            aliases.add(raw.casefold())
            token = self._parameter_alias_token(raw)
            if token:
                aliases.add(token)
        return aliases

    def _participant_parameter_field_names(self, participant: dict[str, Any]) -> set[str]:
        fields: set[str] = set()
        contract = participant.get("parameter_contract") if isinstance(participant.get("parameter_contract"), dict) else {}
        for item in contract.get("parameters") or []:
            if isinstance(item, dict) and str(item.get("name") or "").strip():
                fields.add(str(item.get("name")).strip())
        profile = participant.get("capability_profile") if isinstance(participant.get("capability_profile"), dict) else {}
        for container in (profile, profile.get("tool_summary") if isinstance(profile.get("tool_summary"), dict) else {}):
            schema = container.get("input_schema") if isinstance(container.get("input_schema"), dict) else {}
            props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
            for name in props:
                if str(name).strip():
                    fields.add(str(name).strip())
        return fields

    def _scoped_runtime_parameters_from_values(self, participant: dict[str, Any], runtime_parameters: dict[str, Any]) -> dict[str, Any]:
        """Return only values that belong to this participant.

        The task-level parameter map may contain values for many steps.  This
        method treats unscoped runtime input names as executable input only for
        participants that are explicitly bound to a runtime capability.  Source
        or semantic steps receive no unscoped runtime values, so downstream
        parameters cannot pollute upstream ai_core planning.
        """
        if not isinstance(runtime_parameters, dict):
            return {}
        aliases = self._participant_parameter_aliases(participant)
        field_names = self._participant_parameter_field_names(participant)
        field_tokens = {self._parameter_alias_token(x) for x in field_names}
        executable = self._participant_has_runtime_capability(participant)
        out: dict[str, Any] = {}
        for key, value in runtime_parameters.items():
            if value in (None, "", [], {}):
                continue
            text_key = str(key or "").strip()
            if not text_key or text_key.startswith("_"):
                continue
            lower = text_key.casefold()
            token = self._parameter_alias_token(text_key)
            matched = False
            if "." in text_key:
                prefix, tail = text_key.rsplit(".", 1)
                if prefix.casefold() in aliases or self._parameter_alias_token(prefix) in aliases:
                    out[str(tail).strip()] = copy.deepcopy(value)
                    matched = True
            if matched:
                continue
            for alias in aliases:
                if not alias:
                    continue
                dotted = alias + "."
                underscored = alias + "_"
                if lower.startswith(dotted):
                    out[text_key[len(dotted):]] = copy.deepcopy(value)
                    matched = True
                    break
                if token.startswith(underscored):
                    tail_token = token[len(underscored):]
                    field = next((name for name in field_names if self._parameter_alias_token(name) == tail_token), tail_token)
                    out[field] = copy.deepcopy(value)
                    matched = True
                    break
            if matched:
                continue
            if executable and field_names and (text_key in field_names or token in field_tokens):
                field = next((name for name in field_names if name == text_key or self._parameter_alias_token(name) == token), text_key)
                out[field] = copy.deepcopy(value)
        return out

    def _participant_has_runtime_capability(self, participant: dict[str, Any]) -> bool:
        if not isinstance(participant, dict):
            return False
        profile = participant.get("capability_profile") if isinstance(participant.get("capability_profile"), dict) else {}
        if profile:
            if profile.get("tool_id") or profile.get("capability") or profile.get("capability_type"):
                return True
            if isinstance(profile.get("tool_summary"), dict):
                return True
        policy = str(participant.get("execution_policy") or "").strip().casefold()
        if policy in {"runtime_registered_tool", "registered_runtime_tool", "runtime_tool"}:
            return True
        return False

    def _participant_workflow_step_type(self, participant: dict[str, Any], task_graph: dict[str, Any] | None = None) -> str:
        if not isinstance(participant, dict):
            return ""
        value = str(participant.get("workflow_step_type") or participant.get("step_type") or "").strip()
        if value:
            return value
        pid = self._participant_identity(participant)
        if isinstance(task_graph, dict):
            for task in task_graph.get("tasks") or []:
                if isinstance(task, dict) and str(task.get("participant_id") or "") == pid:
                    return str(task.get("step_type") or task.get("workflow_step_type") or "").strip()
        return ""

    def _participant_is_decomposed_source_step(self, participant: dict[str, Any], task_graph: dict[str, Any] | None = None) -> bool:
        return self._participant_workflow_step_type(participant, task_graph) == "semantic_intermediate_step"

    def _merged_runtime_parameters(self, task_graph: dict[str, Any], participant: dict[str, Any]) -> dict[str, Any]:
        if self._participant_is_decomposed_source_step(participant, task_graph):
            # Decomposed source steps are executed as clean user requests by
            # ai_core. Runtime parameters belong to concrete executable
            # participants/capabilities and must not be injected into these
            # source-step prompts.
            return {}
        values: dict[str, Any] = {}
        if isinstance(task_graph.get("runtime_parameters"), dict):
            values.update(self._scoped_runtime_parameters_from_values(participant, task_graph.get("runtime_parameters") or {}))
        if isinstance(participant.get("runtime_parameters"), dict):
            values.update(self._scoped_runtime_parameters_from_values(participant, participant.get("runtime_parameters") or {}))
        return values

    def _compact_parameter_contract(self, contract: Any) -> dict[str, Any]:
        if not isinstance(contract, dict):
            return {}
        out = {"parameters": []}
        params = contract.get("parameters") if isinstance(contract.get("parameters"), list) else []
        for param in params:
            if not isinstance(param, dict):
                continue
            out["parameters"].append({
                "name": param.get("name"),
                "type": param.get("type") or "list",
                "required": bool(param.get("required", True)),
                "values": param.get("values") if isinstance(param.get("values"), list) else [],
            })
        return out


    def _apply_task_runtime_parameters_to_selected(self, participants: list[dict[str, Any]], runtime_parameters: Any) -> None:
        """Apply current task-run parameters to participant copies only.

        This lets commands such as `parameter=value` or UI-provided values satisfy
        agent parameter contracts for the current run without persisting those
        values to the agent profile.  The full task-run parameter map is also
        copied onto the in-memory participant so schema-driven registered-tool
        binding and repair resume can use generic structural context such as
        original source material and extracted structural spans.  The registered
        tool bridge still filters by the declared tool schema before execution.
        """
        if not isinstance(runtime_parameters, dict) or not runtime_parameters:
            return
        for participant in participants:
            if not isinstance(participant, dict):
                continue
            scoped_values = self._scoped_runtime_parameters_from_values(participant, runtime_parameters)
            if scoped_values:
                scoped = participant.setdefault("runtime_parameters", {})
                if isinstance(scoped, dict):
                    for key, value in scoped_values.items():
                        if value not in (None, "", [], {}) and key not in scoped:
                            scoped[key] = copy.deepcopy(value)
                self.parameter_contract_service.apply_values(participant, scoped_values)
            else:
                self.parameter_contract_service.apply_values(participant, {})

    def _collect_missing_agent_parameter_fields(self, participants: list[dict[str, Any]], dependency_plan: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        fields: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for participant in participants:
            # If the agent is explicitly bound to uploaded artifacts, the real
            # executable parameter contract is owned by artifact introspection
            # in execution_preparation, not by the durable agent profile.
            # This avoids asking stale or inferred agent-level fields before the
            # uploaded file has been inspected. The UI will receive the concrete
            # runtime fields produced from the artifact callable/signature.
            if self._uses_uploaded_artifact_runtime(participant):
                continue
            owner = self._participant_identity(participant) or self._participant_name(participant)
            participant_fields = list(self.parameter_contract_service.to_missing_input_fields(participant))
            participant_fields.extend(self._capability_required_fields(participant))
            for field in participant_fields:
                if not isinstance(field, dict):
                    continue
                if not self._is_blocking_agent_parameter_field(participant, field):
                    continue
                if self._is_approval_parameter_field(field) and self._approval_trusted(participant=participant, tool_id=self._participant_tool_id(participant)):
                    continue
                if self._runtime_field_already_bound(participant, field):
                    continue
                if self._can_defer_field_to_dependency_output(participant, field, dependency_plan or {}):
                    continue
                field_name = str(field.get("name") or field.get("field") or field.get("key") or "").strip()
                key = (owner, field_name)
                if key in seen:
                    continue
                seen.add(key)
                fields.append(field)
        return fields

    def _runtime_field_already_bound(self, participant: dict[str, Any], field: dict[str, Any]) -> bool:
        """Return True when a missing field is already satisfied in run state.

        This is a generic guard against stale parameter_contract.missing_information.
        It checks the current participant runtime_parameters using the same
        participant-id/name scoped alias rules used by task creation and resume.
        """
        if not isinstance(field, dict):
            return False
        name = str(field.get("parameter_name") or field.get("name") or field.get("field") or field.get("key") or "").strip()
        if "." in name:
            name = name.rsplit(".", 1)[-1]
        if not name:
            return False
        values = participant.get("runtime_parameters") if isinstance(participant.get("runtime_parameters"), dict) else {}
        if not isinstance(values, dict):
            return False
        pid = self._participant_identity(participant)
        pname = self._participant_name(participant)
        safe = re.sub(r"[^A-Za-z0-9_]+", "_", pname).strip("_")
        aliases = [name]
        for prefix in (pid, pname, safe):
            if prefix:
                aliases.extend([f"{prefix}.{name}", f"{prefix}_{name}"])
        lowered = {str(k).casefold(): k for k in values.keys()}
        for alias in aliases:
            if alias in values and values[alias] not in (None, "", [], {}):
                return True
            matched = lowered.get(str(alias).casefold())
            if matched is not None and values.get(matched) not in (None, "", [], {}):
                return True
        return False

    def _runtime_value_for_field(self, participant: dict[str, Any], field_name: str) -> Any:
        """Look up a run-scoped value for one participant field.

        This mirrors the alias rules used for missing-field checks and keeps the
        registered-tool dispatch path independent from task/agent names.
        """
        name = str(field_name or "").strip()
        if "." in name:
            name = name.rsplit(".", 1)[-1]
        if not name:
            return None
        values = participant.get("runtime_parameters") if isinstance(participant.get("runtime_parameters"), dict) else {}
        if not isinstance(values, dict):
            return None
        pid = self._participant_identity(participant)
        pname = self._participant_name(participant)
        safe = re.sub(r"[^A-Za-z0-9_]+", "_", pname).strip("_")
        aliases = [name]
        for prefix in (pid, pname, safe):
            if prefix:
                aliases.extend([f"{prefix}.{name}", f"{prefix}_{name}"])
        lowered = {str(k).casefold(): k for k in values.keys()}
        # Prefer scoped aliases over the plain field when both exist.
        ordered_aliases = [alias for alias in aliases if alias != name] + [name]
        for alias in ordered_aliases:
            if alias in values and values[alias] not in (None, "", [], {}):
                return values[alias]
            matched = lowered.get(str(alias).casefold())
            if matched is not None and values.get(matched) not in (None, "", [], {}):
                return values[matched]
        return None

    def _fill_registered_tool_input_from_runtime(self, participant: dict[str, Any], input_data: dict[str, Any], missing: list[Any]) -> tuple[dict[str, Any], list[str]]:
        """Last-mile schema-value reconciliation before asking the user.

        Task creation stores parameters in a generic runtime map; registered
        tools require a clean schema payload.  If the bridge reports a missing
        field, reconcile once more against the participant runtime map using the
        same alias rules as the UI missing-field filter.  This prevents stale
        missing_information from forcing repeated prompts.
        """
        out = dict(input_data or {})
        still_missing: list[str] = []
        for raw in missing or []:
            name = str(raw or "").strip()
            if not name:
                continue
            if out.get(name) not in (None, "", [], {}):
                continue
            value = self._runtime_value_for_field(participant, name)
            if value in (None, "", [], {}):
                still_missing.append(name)
            else:
                out[name] = value
        return out, still_missing

    def _capability_required_fields(self, participant: dict[str, Any]) -> list[dict[str, Any]]:
        """Build missing input fields from runtime capability metadata.

        This is capability-contract based. It does not inspect participant names
        and it does not use example phrases. It only reads fields produced by
        the runtime planner, such as a declared query parameter for a generated
        retrieval step.
        """
        profile = participant.get("capability_profile") if isinstance(participant.get("capability_profile"), dict) else {}
        if not profile:
            return []
        values = participant.get("runtime_parameters") if isinstance(participant.get("runtime_parameters"), dict) else {}
        out: list[dict[str, Any]] = []
        query_name = str(profile.get("query_parameter") or "").strip()
        if profile.get("requires_user_query") is True and query_name:
            if not self._first_scalar(values.get(query_name)):
                pid = self._participant_identity(participant)
                pname = self._participant_name(participant)
                out.append({
                    "kind": "agent_parameter_required",
                    "field": f"{pid}.{query_name}" if pid else query_name,
                    "name": f"{pid}.{query_name}" if pid else query_name,
                    "parameter_name": query_name,
                    "participant_id": pid,
                    "participant_name": pname,
                    "label": " ".join(part.capitalize() for part in query_name.replace("_", " ").split()),
                    "message": "Runtime input is required before this step can continue.",
                    "input_type": "text",
                    "required": True,
                    "runtime_required": True,
                    "blocking": True,
                    "execution_required": True,
                    "resolution_layer": "execution_input",
                    "input_role": "query",
                })
        return out

    def _is_blocking_agent_parameter_field(self, participant: dict[str, Any], field: dict[str, Any]) -> bool:
        """Return True only for explicitly blocking runtime parameters.

        LLM-inferred agent profile slots are advisory by default. They describe
        what a reusable role may need, but they must not block task execution
        unless the profile or parameter explicitly marks them as blocking. This
        keeps durable profile metadata separate from executable runtime inputs.
        Concrete uploaded-artifact callable parameters are collected by the
        artifact preflight path and are not handled here.
        """
        if not isinstance(field, dict):
            return False
        contract = participant.get("parameter_contract") if isinstance(participant.get("parameter_contract"), dict) else {}
        policy = contract.get("collection_policy") if isinstance(contract.get("collection_policy"), dict) else {}
        explicit = (
            field.get("runtime_required") is True
            or field.get("blocking") is True
            or field.get("execution_required") is True
            or policy.get("blocking") is True
        )
        if explicit:
            return True
        if self._looks_like_file_material_contract(participant):
            if self._field_is_runtime_default_output_location(field):
                return False
            return bool(field.get("required", True))

        # Backward compatibility for older runtime-generated participant records:
        # if a contract describes a user-facing content deliverable but was
        # generated before blocking metadata existed, keep the task safely
        # paused until its task-run constraints are provided.  This check uses
        # generic contract shape/objective semantics only; it does not depend on
        # any participant name or domain vocabulary.
        objective = " ".join(str(participant.get(k) or "") for k in ("execution_objective", "instruction", "definition_instruction", "objective"))
        if self.parameter_contract_service._looks_like_content_output_capability(objective):
            # Runtime-generated contracts may use task-specific names instead of
            # the generic fallback names.  For a user-facing content capability,
            # any required missing contract field is blocking for that run.  This
            # keeps the decision based on contract shape and objective semantics,
            # not on participant names or fixed example phrases.
            return bool(field.get("required", True))
        return False


    def _participant_dependency_ids(self, participant: dict[str, Any], dependency_plan: dict[str, Any] | None) -> set[str]:
        pid = self._participant_identity(participant)
        plan = (dependency_plan or {}).get("participants") if isinstance(dependency_plan, dict) else {}
        item = plan.get(pid) if isinstance(plan, dict) else {}
        return {str(x) for x in (item or {}).get("depends_on") or [] if str(x)}

    def _field_text(self, field: dict[str, Any]) -> str:
        return " ".join(str(field.get(k) or "") for k in ("name", "field", "key", "label", "description")).lower()

    def _field_accepts_upstream_material(self, field: dict[str, Any]) -> bool:
        text = self._field_text(field)
        return bool(re.search(r"\b(content|body|text|payload|data|material|input)\b", text, flags=re.I))

    def _field_is_runtime_default_output_location(self, field: dict[str, Any]) -> bool:
        text = self._field_text(field)
        return bool(re.search(r"\b(path|directory|folder|location|output path|save path)\b", text, flags=re.I))

    def _can_defer_field_to_dependency_output(self, participant: dict[str, Any], field: dict[str, Any], dependency_plan: dict[str, Any]) -> bool:
        if self._field_is_runtime_default_output_location(field):
            return self._looks_like_file_material_contract(participant)
        if not self._field_accepts_upstream_material(field):
            return False
        if bool(self._participant_dependency_ids(participant, dependency_plan)):
            return True
        # Some fallback graph records store only edge objects.  Use those edges as
        # a secondary generic dataflow signal without relying on participant names
        # or domain-specific parameter labels.
        pid = self._participant_identity(participant)
        pname = self._participant_name(participant)
        edges = dependency_plan.get("edges") if isinstance(dependency_plan, dict) else []
        if isinstance(edges, list):
            for edge in edges:
                if not isinstance(edge, dict):
                    continue
                target = str(edge.get("to") or edge.get("target") or edge.get("target_id") or "")
                if target and target in {pid, pname}:
                    return True
        return False

    def _contract_fields(self, participant: dict[str, Any]) -> list[dict[str, Any]]:
        contract = participant.get("parameter_contract") if isinstance(participant.get("parameter_contract"), dict) else {}
        params = contract.get("parameters") if isinstance(contract.get("parameters"), list) else []
        return [p for p in params if isinstance(p, dict)]

    def _field_name(self, field: dict[str, Any]) -> str:
        return str(field.get("name") or field.get("field") or field.get("key") or "").strip()

    def _extract_primary_material_from_result(self, result: Any) -> str:
        """Extract the primary public material for a completed upstream result.

        This is intentionally aligned with WorkflowOutputResolver.  It never
        falls back to pipeline stage names or arbitrary status strings; if no
        terminal/public output exists, it returns an empty string so downstream
        side-effecting nodes are blocked instead of receiving internal text.
        """
        if result is None:
            return ""
        fields = self.workflow_output_resolver.extract_public_fields(result)
        for key in ("final_answer", "answer", "result", "text", "content", "material", "output"):
            value = fields.get(key)
            if self._is_public_dependency_material(value):
                return str(value).strip()
        for value in fields.values():
            if self._is_public_dependency_material(value):
                return str(value).strip()
        return ""


    def _binding_task_graph_for_name(self, task_name: str) -> dict[str, Any] | None:
        """Load a task graph shape suitable for workflow-output binding.

        Runtime execution now supports compiled task directories as the source of
        truth.  Side-effecting tools must resolve templates against that compiled
        payload graph, not only against the legacy flat task JSON file.
        """
        if not task_name:
            return None
        flat = self.store.read_json(f"generated/tasks/{task_name}.json")
        if isinstance(flat, dict) and isinstance(flat.get("tasks"), list):
            return flat
        base = Path(self.store.root) / "generated" / "tasks" / str(task_name)
        if not base.exists() or not base.is_dir():
            return flat if isinstance(flat, dict) else None
        graph = self._read_json_file(base / "graph.json")
        manifest = self._read_json_file(base / "task_manifest.json")
        bindings = self._read_json_file(base / "bindings.json")
        steps: list[dict[str, Any]] = []
        if isinstance(graph, dict) and isinstance(graph.get("steps"), list):
            steps = [copy.deepcopy(x) for x in graph.get("steps") if isinstance(x, dict)]
        elif isinstance(manifest, dict) and isinstance(manifest.get("steps"), list):
            steps = [copy.deepcopy(x) for x in manifest.get("steps") if isinstance(x, dict)]
        tasks: list[dict[str, Any]] = []
        for idx, step in enumerate(steps, start=1):
            sid = str(step.get("step_id") or step.get("id") or f"step_{idx:03d}").strip()
            participant_id = str(step.get("participant_id") or step.get("participant") or sid).strip()
            name = str(step.get("name") or step.get("instruction") or sid).strip()
            tasks.append({
                **step,
                "id": sid,
                "step_id": sid,
                "compiled_step_id": sid,
                "source_step_id": sid,
                "participant_id": participant_id,
                "display_name": name,
                "name": name,
            })
        if not tasks and isinstance(flat, dict):
            return flat
        return {
            "task_name": task_name,
            "graph_id": task_name,
            "tasks": tasks,
            "bindings": bindings.get("bindings") if isinstance(bindings, dict) and isinstance(bindings.get("bindings"), list) else [],
            "compiled_task": True,
        }

    def _read_json_file(self, path: Path) -> dict[str, Any]:
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}
        return {}

    def _resolve_task_variable_placeholders_for_participant(
        self,
        *,
        participant: dict[str, Any],
        completed_results: list[Any],
        dependency_plan: dict[str, Any],
        task_graph: dict[str, Any] | None = None,
    ) -> None:
        """Resolve explicit workflow-output placeholders in participant state.

        The resolver is generic: it does not know what any capability does.  It
        only replaces explicit references such as ``{{Step N.field}}`` with
        exportable output from an already completed upstream step.  Because
        parameter bridges may later rebuild input values from parameter-contract
        field containers, this method resolves all common value-bearing slots in
        those field containers, not only ``runtime_parameters``.
        """
        if not isinstance(participant, dict) or not completed_results:
            return
        refs = self._task_variable_reference_map(
            completed_results=completed_results,
            dependency_plan=dependency_plan,
            participant=participant,
            task_graph=task_graph,
        )
        if not refs:
            return
        changed = False
        values = dict(participant.get("runtime_parameters") or {}) if isinstance(participant.get("runtime_parameters"), dict) else {}
        resolved_values = self.workflow_output_resolver.resolve(values, refs)
        if isinstance(resolved_values.value, dict) and resolved_values.value != values:
            values = resolved_values.value
            participant["runtime_parameters"] = values
            changed = True

        contract = participant.get("parameter_contract") if isinstance(participant.get("parameter_contract"), dict) else {}
        params = contract.get("parameters") if isinstance(contract.get("parameters"), list) else []
        value_slots = ("value", "values", "default", "default_value", "example", "examples", "resolved_value", "runtime_value")
        for param in params:
            if not isinstance(param, dict):
                continue
            for slot in value_slots:
                if slot not in param:
                    continue
                resolved = self.workflow_output_resolver.resolve(param.get(slot), refs, f"parameter.{slot}")
                if resolved.value != param.get(slot):
                    param[slot] = resolved.value
                    changed = True
            name = self._field_name(param)
            if name and name in values:
                param_values = param.get("values") if isinstance(param.get("values"), list) else []
                if param.get("value") in (None, "", [], {}) and not param_values:
                    param["value"] = values.get(name)
                    changed = True
        if changed:
            participant["runtime_parameters"] = values
            self.parameter_contract_service.apply_values(participant, values)

    def _task_variable_reference_map(self, *, completed_results: list[Any], dependency_plan: dict[str, Any], participant: dict[str, Any], task_graph: dict[str, Any] | None = None) -> dict[str, Any]:
        """Build public workflow-output references for downstream binding.

        This method is now a compatibility wrapper around the generic
        WorkflowOutputResolver.  It intentionally supports arbitrary upstream
        step aliases and field names declared by the workflow, instead of a
        fixed ``Step1`` convention.
        """
        deps = set(self._participant_dependency_ids(participant, dependency_plan))
        return self.workflow_output_resolver.build_reference_map(
            completed_results=completed_results,
            dependency_ids=deps,
            task_graph=task_graph,
        )

    def _task_step_aliases_for_result(self, *, result_pid: str, result_name: str, task_graph: dict[str, Any] | None) -> list[str]:
        return self.workflow_output_resolver.aliases_for_result(
            absolute_index=1,
            included_index=1,
            result_pid=result_pid,
            result_name=result_name,
            task_graph=task_graph,
        )

    def _resolve_task_variable_templates(self, value: Any, refs: dict[str, Any]) -> Any:
        return self.workflow_output_resolver.resolve(value, refs).value

    def _collect_unresolved_task_templates(self, value: Any, path: str = "") -> list[dict[str, Any]]:
        """Return unresolved ``{{...}}`` task placeholders before side effects."""
        if isinstance(value, dict):
            findings: list[dict[str, Any]] = []
            for key, item in value.items():
                child = f"{path}.{key}" if path else str(key)
                findings.extend(self._collect_unresolved_task_templates(item, child))
            return findings
        if isinstance(value, list):
            findings = []
            for idx, item in enumerate(value):
                child = f"{path}[{idx}]" if path else f"[{idx}]"
                findings.extend(self._collect_unresolved_task_templates(item, child))
            return findings
        if isinstance(value, str) and "{{" in value and "}}" in value:
            refs = [m.group(1).strip() for m in re.finditer(r"\{\{\s*([^{}]+?)\s*\}\}", value)]
            return [{"path": path or "$", "references": refs, "value_preview": value[:240]}]
        return []

    def _normalize_task_variable_key(self, value: Any) -> str:
        return self.workflow_output_resolver.normalize_key(value)

    def _dependency_material_text(self, participant: dict[str, Any], completed_results: list[Any], dependency_plan: dict[str, Any]) -> str:
        deps = self._participant_dependency_ids(participant, dependency_plan)
        materials: list[str] = []
        for result in completed_results:
            result_pid = str(getattr(result, "participant_id", "") or "")
            result_name = str(getattr(result, "participant_name", "") or "")
            if deps and result_pid not in deps and result_name not in deps:
                continue
            if not self._dependency_result_is_available(result):
                continue
            material = self._extract_primary_material_from_result(result)
            if material:
                materials.append(material)
        return "\n\n".join(materials).strip()

    def _bind_dependency_outputs_to_participant(self, *, participant: dict[str, Any], completed_results: list[Any], dependency_plan: dict[str, Any]) -> None:
        material = self._dependency_material_text(participant, completed_results, dependency_plan)
        if not material:
            return
        values = dict(participant.get("runtime_parameters") or {}) if isinstance(participant.get("runtime_parameters"), dict) else {}
        changed = False
        has_declared_dependencies = bool(self._participant_dependency_ids(participant, dependency_plan))
        for field in self._contract_fields(participant):
            name = self._field_name(field)
            if not name or not self._field_accepts_upstream_material(field):
                continue
            current = values.get(name)
            # For declared dataflow edges, upstream verified material is the
            # source of truth for generic content/material input fields.  This
            # prevents a placeholder typed during parameter collection from
            # replacing the actual upstream result.
            if has_declared_dependencies or current in (None, "", [], {}):
                # Store upstream material as a single list item so generic
                # parameter normalization never splits long text on commas or
                # newlines.  The dependency result remains the source of truth
                # for this run and is not persisted to the durable participant.
                normalized_material = [material]
                if current != normalized_material:
                    values[name] = normalized_material
                    changed = True
        if changed:
            participant["runtime_parameters"] = values
            self.parameter_contract_service.apply_values(participant, values)

    def _looks_like_file_material_contract(self, participant: dict[str, Any]) -> bool:
        fields = self._contract_fields(participant)
        if not fields:
            return False
        joined = " ".join(self._field_text(field) for field in fields)
        has_output_container = bool(re.search(r"\b(file|document|artifact)\b", joined, flags=re.I))
        has_material = any(self._field_accepts_upstream_material(field) for field in fields)
        has_name_or_format = bool(re.search(r"\b(name|format|type|extension|mime)\b", joined, flags=re.I))
        return has_output_container and has_material and has_name_or_format

    def _value_for_field_role(self, participant: dict[str, Any], pattern: str) -> Any:
        values = participant.get("runtime_parameters") if isinstance(participant.get("runtime_parameters"), dict) else {}
        for field in self._contract_fields(participant):
            if re.search(pattern, self._field_text(field), flags=re.I):
                name = self._field_name(field)
                if name and values.get(name) not in (None, "", [], {}):
                    return values.get(name)
                field_values = field.get("values") if isinstance(field.get("values"), list) else []
                if field_values:
                    return field_values
        return None

    def _first_scalar(self, value: Any) -> str:
        if isinstance(value, list):
            for item in value:
                text = self._first_scalar(item)
                if text:
                    return text
            return ""
        if isinstance(value, dict):
            for key in ("value", "text", "content", "name"):
                if key in value:
                    text = self._first_scalar(value.get(key))
                    if text:
                        return text
            return ""
        return str(value or "").strip()

    def _safe_download_filename(self, name: str, fmt: str) -> str:
        base = Path(str(name or "generated_output")).name.strip() or "generated_output"
        ext = re.sub(r"[^A-Za-z0-9]", "", str(fmt or "txt").lower()) or "txt"
        if ext == "text":
            ext = "txt"
        if not Path(base).suffix:
            base = f"{base}.{ext}"
        return re.sub(r"[^A-Za-z0-9._-]", "_", base) or f"generated_output.{ext}"

    async def _try_execute_generated_capability(
        self,
        *,
        participant: dict[str, Any],
        completed_results: list[Any],
        dependency_plan: dict[str, Any],
        task_name: str,
    ) -> AgentExecutionResult | None:
        profile = participant.get("capability_profile") if isinstance(participant.get("capability_profile"), dict) else {}
        capability_type = str(profile.get("capability_type") or "").strip()
        if capability_type == "runtime_registered_tool":
            return await self._execute_registered_tool_capability(participant=participant, task_name=task_name, completed_results=completed_results, dependency_plan=dependency_plan)
        if capability_type == "image_generation":
            return await self._execute_image_generation_capability(participant=participant, completed_results=completed_results, dependency_plan=dependency_plan)
        if capability_type == "video_generation":
            return await self._execute_video_generation_capability(participant=participant, completed_results=completed_results, dependency_plan=dependency_plan)
        if capability_type != "local_knowledge_retrieval":
            return None
        values = participant.get("runtime_parameters") if isinstance(participant.get("runtime_parameters"), dict) else {}
        query_name = str(profile.get("query_parameter") or "").strip()
        query = self._first_scalar(values.get(query_name)) if query_name else ""
        if not query:
            for field in self._contract_fields(participant):
                if str(field.get("input_role") or "") == "query":
                    query = self._first_scalar(values.get(self._field_name(field)))
                    if query:
                        break
        if not query:
            return AgentExecutionResult(
                participant_id=self._participant_identity(participant),
                participant_name=self._participant_name(participant),
                core_run_id=new_id("capability_missing_input"),
                status="requires_input",
                final_answer="",
                workflow_results={"status": "requires_input", "capability_type": capability_type},
                pending_action={
                    "kind": "agent_parameter_collection",
                    "message": "Runtime input is required before execution can continue.",
                    "request": {"input_mode": "multi_value_list", "fields": self.parameter_contract_service.to_missing_input_fields(participant)},
                },
                missing_inputs=self.parameter_contract_service.to_missing_input_fields(participant),
                origin="auxiliary_brain",
            )
        answer_payload = await self.knowledge_service.rag_answer(query=query, synthesize=True)
        answer = str(answer_payload.get("answer") or answer_payload.get("answer_material") or "").strip()
        status = "completed" if answer else "failed"
        return AgentExecutionResult(
            participant_id=self._participant_identity(participant),
            participant_name=self._participant_name(participant),
            core_run_id=new_id("knowledge_result"),
            status=status,
            final_answer=answer or "No verified local knowledge result was produced.",
            workflow_results={
                "status": status,
                "capability_type": capability_type,
                "query": query,
                "rag_answer": answer_payload,
                "verified_result_material": {"type": "text", "text": answer, "source": "local_knowledge"},
            },
            origin="auxiliary_brain",
        )

    def _ensure_participant_structural_context(self, *, participant: dict[str, Any], task_name: str) -> None:
        """Ensure delegated registered-tool participants carry source spans.

        The first execution and later repair resume both run through participant
        copies.  If a copied participant is missing generic source material,
        recover it from the durable task graph and task step fragments.  This
        keeps repair deterministic without adding capability-specific rules.
        """
        if not isinstance(participant, dict):
            return
        values = participant.setdefault("runtime_parameters", {})
        if not isinstance(values, dict):
            values = {}
            participant["runtime_parameters"] = values
        has_material = bool(str(values.get("_original_user_material") or values.get("_source_text") or "").strip())
        has_structural = isinstance(values.get("_detected_structural_values"), dict) and bool(values.get("_detected_structural_values"))
        if has_material and has_structural:
            return
        task_graph = self.store.read_json(f"generated/tasks/{task_name}.json") if task_name else None
        source_material = self._task_source_material(task_graph=task_graph if isinstance(task_graph, dict) else {}, fallback_values=[values.get("_source_text")])
        if source_material and not has_material:
            values.setdefault("_original_user_material", source_material)
            values.setdefault("_source_text", source_material)
        if not has_structural:
            structural = self._extract_structural_values_from_material(source_material or values.get("_original_user_material") or values.get("_source_text"))
            if structural:
                values.setdefault("_detected_structural_values", structural)

    def _ensure_task_runtime_parameters_for_participant(self, *, participant: dict[str, Any], task_name: str) -> None:
        """Hydrate a participant copy with durable task-run parameters.

        This is a generic task/participant binding guard.  A task graph is a
        durable execution snapshot; participant copies created during resume or
        capability dispatch must not lose values that were already parsed from
        the task instruction.  The method only merges runtime parameter maps and
        applies the existing parameter contract service; it does not inspect
        capability names or business words.
        """
        if not isinstance(participant, dict) or not task_name:
            return
        task_graph = self.store.read_json(f"generated/tasks/{task_name}.json")
        if not isinstance(task_graph, dict):
            return
        values = task_graph.get("runtime_parameters") if isinstance(task_graph.get("runtime_parameters"), dict) else {}
        if not values:
            return
        scoped = participant.setdefault("runtime_parameters", {})
        if not isinstance(scoped, dict):
            scoped = {}
            participant["runtime_parameters"] = scoped
        changed = False
        for key, value in values.items():
            if value not in (None, "", [], {}) and key not in scoped:
                scoped[key] = copy.deepcopy(value)
                changed = True
        if changed:
            self.parameter_contract_service.apply_values(participant, scoped)

    _REGISTERED_TOOL_EXECUTION_CONTROL_NAMES = {"approval_confirmed", "remember_approval", "confirm", "confirmed", "approval", "approved"}

    def _execution_control_tail(self, key: Any) -> str:
        return str(key or "").strip().rsplit(".", 1)[-1].replace("-", "_").casefold()

    def _separate_registered_tool_approval_controls(self, *, input_data: dict[str, Any], missing: list[Any], approval_confirmed: bool) -> tuple[dict[str, Any], list[Any]]:
        """Handle approval controls before ordinary input collection.

        Approval controls are not business parameters. If a tool/profile is
        already auto-approved by policy, approval fields are removed from the
        missing-input list. Otherwise they stay missing so the runtime can ask for
        confirmation. Submitted control values remain available in
        runtime_parameters and are forwarded to the registered tool executor as
        execution-control arguments, not as capability business input.
        """
        cleaned_input = dict(input_data or {})
        cleaned_missing: list[Any] = []
        for item in missing or []:
            tail = self._execution_control_tail(item)
            if tail in self._REGISTERED_TOOL_EXECUTION_CONTROL_NAMES and approval_confirmed:
                continue
            cleaned_missing.append(item)
        return cleaned_input, cleaned_missing

    def _registered_tool_business_input(self, *, input_data: dict[str, Any], participant: dict[str, Any]) -> dict[str, Any]:
        """Return schema/projected business input for runtime tool execution.

        The bridge may carry approval controls alongside business values. This
        method keeps the executable tool payload aligned with the registered
        schema without using capability-specific names.
        """
        profile = participant.get("capability_profile") if isinstance(participant.get("capability_profile"), dict) else {}
        input_schema = profile.get("input_schema") if isinstance(profile.get("input_schema"), dict) else {}
        props = input_schema.get("properties") if isinstance(input_schema.get("properties"), dict) else {}
        additional_allowed = input_schema.get("additionalProperties", True) is not False
        out: dict[str, Any] = {}
        for key, value in dict(input_data or {}).items():
            tail = self._execution_control_tail(key)
            if tail in self._REGISTERED_TOOL_EXECUTION_CONTROL_NAMES and key not in props:
                continue
            if additional_allowed or key in props:
                out[key] = value
        return out


    def _normalize_registered_tool_presentation_input(self, *, input_data: dict[str, Any], participant: dict[str, Any]) -> dict[str, Any]:
        """Normalize structured/media-rich values before side-effect execution.

        The rule is schema-driven and presentation-generic: if a registered tool
        declares text/html/attachment-like fields, upstream dict/list material is
        converted into safe scalar text/html values.  This keeps the runtime
        reusable and avoids capability-specific branching.
        """
        if not isinstance(input_data, dict):
            return {}
        profile = participant.get("capability_profile") if isinstance(participant.get("capability_profile"), dict) else {}
        schema = profile.get("input_schema") if isinstance(profile.get("input_schema"), dict) else {}
        props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        if not props:
            return input_data
        out = dict(input_data)
        normalized_by_key: dict[str, dict[str, Any]] = {}

        def normalize_value(key: str, value: Any) -> dict[str, Any]:
            if key not in normalized_by_key:
                normalized_by_key[key] = self.output_normalizer.normalize(value)
            return normalized_by_key[key]

        # Scalar string fields should not receive raw dict/list objects.
        for key, spec in props.items():
            if key not in out:
                continue
            expected = spec.get("type") if isinstance(spec, dict) else None
            if isinstance(expected, list):
                expected = next((x for x in expected if x != "null"), expected[0] if expected else None)
            value = out.get(key)
            if expected == "string" and isinstance(value, (dict, list, tuple, set)):
                out[key] = str(normalize_value(str(key), value).get("text") or "")

        # If a declared html-like field is empty, derive it from the richest
        # available content-like field.  Names are generic presentation roles.
        html_keys = [k for k in props if str(k).replace("-", "_").casefold() in {"html", "html_body", "body_html", "content_html"}]
        text_keys = [k for k in props if str(k).replace("-", "_").casefold() in {"body", "text", "content", "message", "final_answer", "answer"}]
        attachment_keys = [k for k in props if str(k).replace("-", "_").casefold() in {"attachments", "files", "file_paths"}]
        source_key = next((k for k in text_keys if out.get(k) not in (None, "", [], {})), None)
        rich_key = next((k for k in out.keys() if str(k).replace("-", "_").casefold() in {"presentation_html", "html"} and out.get(k) not in (None, "", [], {})), None)
        if source_key:
            normalized = normalize_value(str(source_key), out.get(source_key))
            for html_key in html_keys:
                if out.get(html_key) in (None, "", [], {}):
                    out[html_key] = str(out.get(rich_key) if rich_key else normalized.get("html") or "")
            for attachment_key in attachment_keys:
                if out.get(attachment_key) in (None, "", [], {}):
                    out[attachment_key] = normalized.get("attachments") or []
        return out

    def _resolve_executable_input_templates(
        self,
        *,
        input_data: dict[str, Any],
        participant: dict[str, Any],
        completed_results: list[Any],
        dependency_plan: dict[str, Any],
        task_graph: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        """Resolve templates at the final executable-input boundary.

        Earlier phases normalize participant state.  The parameter bridge can
        still rebuild executable input from schema/contract containers, so the
        last safe point before side effects must resolve explicit templates
        again.  The first pass honors declared dependency scope.  If unresolved
        placeholders remain, a second pass allows explicit step aliases from all
        completed results; this fixes stale or missing dependency metadata while
        still requiring a user-declared ``{{...}}`` reference.
        """
        if not isinstance(input_data, dict):
            return {}, [], []
        scoped_refs = self._task_variable_reference_map(
            completed_results=completed_results,
            dependency_plan=dependency_plan,
            participant=participant,
            task_graph=task_graph,
        )
        first = self.workflow_output_resolver.resolve(input_data, scoped_refs, "input") if scoped_refs else None
        resolved_value = first.value if first is not None and isinstance(first.value, dict) else dict(input_data)
        unresolved = list(first.unresolved) if first is not None else self._collect_unresolved_task_templates(resolved_value)
        debug: list[dict[str, Any]] = []
        if first is not None and first.changed:
            debug.append({"scope": "declared_dependencies", "changed": True, "unresolved_count": len(unresolved)})
        if unresolved:
            all_refs = self.workflow_output_resolver.build_reference_map(
                completed_results=completed_results or [],
                dependency_ids=set(),
                task_graph=task_graph,
            )
            if all_refs:
                second = self.workflow_output_resolver.resolve(resolved_value, all_refs, "input")
                if isinstance(second.value, dict):
                    resolved_value = second.value
                    unresolved = list(second.unresolved)
                    debug.append({"scope": "explicit_step_aliases", "changed": bool(second.changed), "unresolved_count": len(unresolved)})
        return resolved_value, unresolved, debug

    def _executable_input_contains_unverified_failure(self, value: Any) -> list[dict[str, Any]]:
        """Detect failure diagnostics before executing side-effect tools.

        This is a generic side-effect safety gate.  It prevents provider errors,
        verification failures, and unresolved runtime diagnostics from being
        materialized into email/chat/export bodies.  It does not inspect task
        or business vocabulary.
        """
        findings: list[dict[str, Any]] = []
        markers = (
            "no real llm provider is available",
            "provider_error_recovered",
            "model request timed out",
            "provider failed",
            "verification failed",
            "source retrieval did not produce",
            "unresolved workflow output references",
            "workflow finished, but no verified",
            "not json serializable",
            "is not json serializable",
            "object of type",
            "runtime_serialization_problem",
            "serialization_failure",
            "registered capability input still contains unresolved",
        )
        def visit(item: Any, path: str = "$") -> None:
            if isinstance(item, dict):
                for k, v in item.items():
                    visit(v, f"{path}.{k}")
                return
            if isinstance(item, list):
                for i, v in enumerate(item):
                    visit(v, f"{path}[{i}]")
                return
            if isinstance(item, str):
                low = item.casefold()
                if any(m in low for m in markers):
                    findings.append({"path": path, "reason": "unverified_failure_material", "preview": item[:240]})
        visit(value)
        return findings

    async def _execute_registered_tool_capability(self, *, participant: dict[str, Any], task_name: str, completed_results: list[Any] | None = None, dependency_plan: dict[str, Any] | None = None) -> AgentExecutionResult | None:
        profile = participant.get("capability_profile") if isinstance(participant.get("capability_profile"), dict) else {}
        tool_id = str(profile.get("tool_id") or "").strip()
        if not tool_id:
            return None
        self._ensure_task_runtime_parameters_for_participant(participant=participant, task_name=task_name)
        task_graph_for_templates = self._binding_task_graph_for_name(task_name) if task_name else None
        self._resolve_task_variable_placeholders_for_participant(
            participant=participant,
            completed_results=completed_results or [],
            dependency_plan=dependency_plan or {},
            task_graph=task_graph_for_templates,
        )
        self._ensure_participant_structural_context(participant=participant, task_name=task_name)
        values = participant.get("runtime_parameters") if isinstance(participant.get("runtime_parameters"), dict) else {}
        profile_id = str(values.get("profile_id") or "default")
        policy_auto_approved = self._approval_trusted(participant=participant, tool_id=tool_id, profile_id=profile_id)
        if policy_auto_approved:
            values = dict(values)
        bridge_result = self.registered_tool_parameter_bridge.build_invocation(participant=participant, provided_values=values)
        input_data = bridge_result.get("input_data") if isinstance(bridge_result.get("input_data"), dict) else {}
        missing = bridge_result.get("missing") if isinstance(bridge_result.get("missing"), list) else []
        input_data, missing = self._separate_registered_tool_approval_controls(input_data=input_data, missing=missing, approval_confirmed=policy_auto_approved)
        if missing:
            input_data, missing = self._fill_registered_tool_input_from_runtime(participant, input_data, missing)
            input_data, missing = self._separate_registered_tool_approval_controls(input_data=input_data, missing=missing, approval_confirmed=policy_auto_approved)
        if missing:
            raw_fields = self.registered_tool_parameter_bridge.input_fields_from_schema(participant=participant)
            missing_set = {str(x).casefold() for x in missing}
            fields = []
            for field in raw_fields:
                pname = str(field.get("parameter_name") or field.get("name") or field.get("field") or "").rsplit(".", 1)[-1]
                if pname.casefold() in missing_set and not self._runtime_field_already_bound(participant, field):
                    fields.append(field)
            if not fields:
                # Values were present but a stale contract still reported missing.
                # Rebuild once from the now-normalized participant state before
                # pausing the run.
                bridge_result = self.registered_tool_parameter_bridge.build_invocation(participant=participant, provided_values=participant.get("runtime_parameters") or {})
                input_data = bridge_result.get("input_data") if isinstance(bridge_result.get("input_data"), dict) else {}
                missing = bridge_result.get("missing") if isinstance(bridge_result.get("missing"), list) else []
                input_data, missing = self._separate_registered_tool_approval_controls(input_data=input_data, missing=missing, approval_confirmed=policy_auto_approved)
                if not missing:
                    pass
                else:
                    fields = [f for f in raw_fields if str(f.get("parameter_name") or "").casefold() in {str(x).casefold() for x in missing}]
            if fields:
                return AgentExecutionResult(
                    participant_id=self._participant_identity(participant),
                    participant_name=self._participant_name(participant),
                    core_run_id=new_id("registered_tool_missing_input"),
                    status="requires_input",
                    final_answer="",
                    workflow_results={"status": "requires_input", "capability_type": "runtime_registered_tool", "tool_id": tool_id},
                    pending_action={
                        "kind": "agent_parameter_collection",
                        "message": "Runtime input is required before execution can continue.",
                        "request": {"input_mode": "multi_value_list", "fields": fields},
                    },
                    missing_inputs=fields,
                    origin="auxiliary_brain",
                )
        executable_input_data = self._registered_tool_business_input(input_data=input_data, participant=participant)
        executable_input_data, unresolved_templates, binding_debug = self._resolve_executable_input_templates(
            input_data=executable_input_data,
            participant=participant,
            completed_results=completed_results or [],
            dependency_plan=dependency_plan or {},
            task_graph=task_graph_for_templates,
        )
        executable_input_data = self._normalize_registered_tool_presentation_input(
            input_data=executable_input_data,
            participant=participant,
        )
        if unresolved_templates:
            return AgentExecutionResult(
                participant_id=self._participant_identity(participant),
                participant_name=self._participant_name(participant),
                core_run_id=new_id("registered_tool_unresolved_template"),
                status="failed",
                final_answer="Registered capability input still contains unresolved workflow output references.",
                workflow_results={
                    "status": "failed",
                    "failure_class": "template_resolution_problem",
                    "capability_type": "runtime_registered_tool",
                    "tool_id": tool_id,
                    "unresolved_templates": unresolved_templates,
                    "binding_debug": binding_debug,
                    "input_keys": sorted(executable_input_data.keys()),
                },
                origin="auxiliary_brain",
            )
        unsafe_material = self._executable_input_contains_unverified_failure(executable_input_data)
        if unsafe_material:
            return AgentExecutionResult(
                participant_id=self._participant_identity(participant),
                participant_name=self._participant_name(participant),
                core_run_id=new_id("registered_tool_unverified_material"),
                status="failed",
                final_answer="Registered capability input contains unverified failure material and was not executed.",
                workflow_results={
                    "status": "failed",
                    "failure_class": "unverified_failure_material",
                    "capability_type": "runtime_registered_tool",
                    "tool_id": tool_id,
                    "unsafe_material": unsafe_material,
                    "binding_debug": binding_debug,
                    "input_keys": sorted(executable_input_data.keys()),
                },
                origin="auxiliary_brain",
            )
        execution_policy = profile.get("execution_policy") if isinstance(profile.get("execution_policy"), dict) else {}
        approval_policy = execution_policy.get("approval_policy") if isinstance(execution_policy.get("approval_policy"), dict) else {}
        approval_confirmed = bool(values.get("approval_confirmed") or values.get("confirm") or values.get("confirmed"))
        if not approval_confirmed and policy_auto_approved:
            approval_confirmed = True
        result = self.registered_tool_service.execute_tool(
            tool_id=tool_id,
            input_data=executable_input_data,
            run_id=new_id("registered_tool_run"),
            profile_id=profile_id,
            approval_confirmed=approval_confirmed,
            remember_approval=bool(values.get("remember_approval")),
        )
        status = str(result.get("status") or "").strip()
        if status == "requires_configuration":
            fields = self._configuration_fields_for_registered_tool(result)
            return AgentExecutionResult(
                participant_id=self._participant_identity(participant),
                participant_name=self._participant_name(participant),
                core_run_id=new_id("registered_tool_config_required"),
                status="requires_input",
                final_answer="",
                workflow_results={"status": "requires_configuration", "tool_id": tool_id, "configuration_status": result.get("configuration_status")},
                pending_action={
                    "kind": "runtime_tool_configuration",
                    "tool_id": tool_id,
                    "message": "Runtime-declared configuration or secret values are required before this capability can execute.",
                    "request": {"input_mode": "runtime_tool_profile", "fields": fields},
                },
                missing_inputs=fields,
                origin="auxiliary_brain",
            )
        if status == "requires_human_confirmation":
            preview = result.get("preview") if isinstance(result.get("preview"), dict) else {}
            return AgentExecutionResult(
                participant_id=self._participant_identity(participant),
                participant_name=self._participant_name(participant),
                core_run_id=new_id("registered_tool_approval_required"),
                status="paused",
                final_answer="",
                workflow_results={"status": "requires_human_confirmation", "tool_id": tool_id, "preview": preview},
                pending_action={
                    "kind": "runtime_tool_human_confirmation",
                    "tool_id": tool_id,
                    "message": "This runtime-generated capability requires confirmation before execution.",
                    "approval_policy": approval_policy or result.get("approval_policy"),
                    "preview": preview,
                    "request": {"input_mode": "confirmation", "fields": [
                        {"field": f"{self._participant_identity(participant)}.approval_confirmed", "name": f"{self._participant_identity(participant)}.approval_confirmed", "label": "Confirm execution", "message": "Check to confirm execution.", "input_type": "boolean", "required": True},
                        {"field": f"{self._participant_identity(participant)}.remember_approval", "name": f"{self._participant_identity(participant)}.remember_approval", "label": "Do not ask again", "message": "Optional: remember this approval for this agent/tool.", "input_type": "boolean", "required": False}
                    ]},
                },
                missing_inputs=[],
                origin="auxiliary_brain",
            )
        ok = bool(result.get("ok"))
        final_answer = self._registered_tool_final_answer(result)
        if not ok:
            repair = result.get("repair") if isinstance(result.get("repair"), dict) else {}
            if repair and (bool(repair.get("requires_user_confirmation")) or bool(repair.get("requires_user_action"))):
                source_material = str(values.get("_original_user_material") or "").strip()
                detected_structural_values = values.get("_detected_structural_values") if isinstance(values.get("_detected_structural_values"), dict) else {}
                if source_material and not detected_structural_values:
                    detected_structural_values = self._extract_structural_values_from_material(source_material)
                repair_resume_checkpoint = {
                    "resume_owner": "auxiliary_brain",
                    "resume_kind": "registered_capability_feedback_repair",
                    "participant_id": self._participant_identity(participant),
                    "participant_name": self._participant_name(participant),
                    "tool_id": tool_id,
                    "failed_input": input_data,
                    "runtime_parameter_keys": sorted(values.keys()),
                    "original_user_material": source_material,
                    "detected_structural_values": detected_structural_values,
                }
                pending = self._build_feedback_repair_pending_action(
                    participant=participant,
                    tool_id=tool_id,
                    repair=repair,
                    result=result,
                    final_answer=final_answer,
                    checkpoint=repair_resume_checkpoint,
                    input_data=input_data,
                )
                return AgentExecutionResult(
                    participant_id=self._participant_identity(participant),
                    participant_name=self._participant_name(participant),
                    core_run_id=new_id("registered_tool_repair_required"),
                    status="paused",
                    final_answer=str(result.get("human_readable_error") or repair.get("user_message") or final_answer),
                    workflow_results={
                        "status": str(repair.get("status") or "repair_required"),
                        "capability_type": "runtime_registered_tool",
                        "tool_id": tool_id,
                        "input_keys": sorted(input_data.keys()),
                        "tool_execution": result,
                        "repair": repair,
                        "repair_resume_checkpoint": repair_resume_checkpoint,
                    },
                    pending_action=pending,
                    missing_inputs=[],
                    origin="auxiliary_brain",
                )
        return AgentExecutionResult(
            participant_id=self._participant_identity(participant),
            participant_name=self._participant_name(participant),
            core_run_id=new_id("registered_tool_result"),
            status="completed" if ok else "failed",
            final_answer=final_answer,
            workflow_results={
                "status": "completed" if ok else "failed",
                "capability_type": "runtime_registered_tool",
                "tool_id": tool_id,
                "input_keys": sorted(input_data.keys()),
                "tool_execution": result,
            },
            origin="auxiliary_brain",
        )


    def _build_feedback_repair_pending_action(
        self,
        *,
        participant: dict[str, Any],
        tool_id: str,
        repair: dict[str, Any],
        result: dict[str, Any],
        final_answer: str,
        checkpoint: dict[str, Any],
        input_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a user interaction for a generic repair route.

        User-owned value/profile issues must not be shown as a blind
        confirmation loop. System-owned generated implementation repairs may be
        confirmed and resumed through the feedback-repair resume path.
        """
        pid = self._participant_identity(participant)
        diagnosis = repair.get("diagnosis") if isinstance(repair.get("diagnosis"), dict) else {}
        category = str(diagnosis.get("category") or "").strip()
        interaction_kind = str(repair.get("interaction_kind") or "").strip()
        base_message = str(repair.get("user_message") or result.get("human_readable_error") or final_answer or "A repair action is required.")
        common = {
            "tool_id": tool_id,
            "repair_id": repair.get("repair_id"),
            "message": base_message,
            "diagnosis": diagnosis,
            "repair": repair,
            "resume_checkpoint": checkpoint,
            "original_user_material": checkpoint.get("original_user_material"),
            "detected_structural_values": checkpoint.get("detected_structural_values") if isinstance(checkpoint.get("detected_structural_values"), dict) else {},
        }
        if interaction_kind == "profile_secret_update_required" or category == "secret_problem":
            return {
                **common,
                "kind": "profile_secret_update_required",
                "request": {
                    "input_mode": "profile_secret_update_required",
                    "fields": [],
                    "message": "Update the selected profile secret values, save them, and retry the task. Secret values cannot be repaired automatically.",
                },
            }
        if interaction_kind == "profile_configuration_update_required" or category == "configuration_problem":
            return {
                **common,
                "kind": "profile_configuration_update_required",
                "request": {
                    "input_mode": "profile_configuration_update_required",
                    "fields": [],
                    "message": "Update the selected profile connection values, save them, and retry the task.",
                },
            }
        if interaction_kind == "input_update_required" or category == "parameter_problem":
            return {
                **common,
                "kind": "runtime_input_update_required",
                "request": {
                    "input_mode": "runtime_input_update_required",
                    "fields": self._repair_input_fields(participant=participant, input_data=input_data),
                    "message": "Correct the runtime input values and submit again. If the original request contained a complete structural value, it is shown in the trace and can be reused.",
                },
            }
        return {
            **common,
            "kind": "feedback_repair_confirmation",
            "request": {"input_mode": "repair_confirmation", "fields": [
                {"field": f"{pid}.repair_confirmed", "name": f"{pid}.repair_confirmed", "label": "Confirm system repair", "message": "Confirm whether the runtime should apply this system-owned repair path.", "input_type": "boolean", "required": True}
            ]},
        }

    def _repair_input_fields(self, *, participant: dict[str, Any], input_data: dict[str, Any]) -> list[dict[str, Any]]:
        pid = self._participant_identity(participant)
        fields: list[dict[str, Any]] = []
        for key in sorted((input_data or {}).keys()):
            fields.append({
                "field": f"{pid}.{key}",
                "name": f"{pid}.{key}",
                "parameter_name": key,
                "participant_id": pid,
                "label": str(key).replace("_", " ").title(),
                "message": f"Review or correct {key}.",
                "input_type": "list" if isinstance((input_data or {}).get(key), list) else "string",
                "required": True,
                "collection_mode": "single_value",
                "runtime_required": True,
                "blocking": True,
                "execution_required": True,
            })
        return fields

    def _build_registered_tool_input(self, *, participant: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
        bridge_result = self.registered_tool_parameter_bridge.build_invocation(participant=participant, provided_values=values)
        return bridge_result.get("input_data") if isinstance(bridge_result.get("input_data"), dict) else {}

    def _missing_registered_tool_inputs(self, *, participant: dict[str, Any], input_data: dict[str, Any]) -> list[str]:
        bridge_result = self.registered_tool_parameter_bridge.build_invocation(participant=participant, provided_values=input_data)
        missing = bridge_result.get("missing") if isinstance(bridge_result.get("missing"), list) else []
        return [str(x) for x in missing]

    def _configuration_fields_for_registered_tool(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        tool = result.get("tool") if isinstance(result.get("tool"), dict) else {}
        fields: list[dict[str, Any]] = []
        for group_name in ("connection_schema", "secret_schema"):
            schema = tool.get(group_name) if isinstance(tool.get(group_name), dict) else {}
            properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
            required = {str(x) for x in schema.get("required", [])} if isinstance(schema.get("required"), list) else set()
            for name, prop in properties.items():
                prop = prop if isinstance(prop, dict) else {}
                fields.append({
                    "kind": "runtime_tool_configuration_required",
                    "field": f"{group_name}.{name}",
                    "name": f"{group_name}.{name}",
                    "parameter_name": str(name),
                    "label": str(prop.get("title") or name),
                    "message": str(prop.get("description") or f"Provide {name}."),
                    "input_type": "secret" if group_name == "secret_schema" else str(prop.get("type") or "string"),
                    "required": str(name) in required,
                    "configuration_group": group_name,
                })
        return fields

    def _registered_tool_final_answer(self, result: dict[str, Any]) -> str:
        if not isinstance(result, dict):
            return "Runtime tool execution returned no structured result."
        tool_id = str(result.get("tool_id") or "runtime tool")
        if result.get("ok"):
            material = self._registered_tool_success_material(result)
            if material:
                return material
            return f"Runtime capability executed successfully: {tool_id}."
        message = "Runtime capability execution failed."
        error = result.get("error") if isinstance(result.get("error"), dict) else {}
        nested = result.get("result") if isinstance(result.get("result"), dict) else {}
        nested_error = nested.get("error") if isinstance(nested.get("error"), dict) else {}
        data = nested.get("data") if isinstance(nested.get("data"), dict) else {}
        candidates = [
            error.get("message") if isinstance(error, dict) else None,
            nested_error.get("message") if isinstance(nested_error, dict) else None,
            nested.get("error") if isinstance(nested.get("error"), str) else None,
            data.get("reason") if isinstance(data, dict) else None,
            result.get("status"),
        ]
        for item in candidates:
            if item not in (None, "", [], {}):
                message = str(item)
                break
        return f"Runtime capability execution failed: {tool_id}. {message}"

    def _registered_tool_success_material(self, result: dict[str, Any]) -> str:
        nested = result.get("result") if isinstance(result.get("result"), dict) else {}
        data = nested.get("data") if isinstance(nested.get("data"), dict) else {}
        if not data:
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
        candidates = [
            nested.get("final_answer"),
            nested.get("message"),
            result.get("final_answer"),
            result.get("message"),
        ]
        for item in candidates:
            text = str(item or "").strip()
            if text and not text.casefold().startswith("runtime capability executed successfully"):
                return text
        if not data:
            return ""
        lines = []
        for key, value in data.items():
            if value in (None, "", [], {}):
                continue
            label = str(key).replace("_", " ")
            lines.append(f"{label}: {value}")
        return "\n".join(lines)



    async def _execute_image_generation_capability(self, *, participant: dict[str, Any], completed_results: list[Any], dependency_plan: dict[str, Any]) -> AgentExecutionResult | None:
        self._bind_dependency_outputs_to_participant(participant=participant, completed_results=completed_results, dependency_plan=dependency_plan)
        values = participant.get("runtime_parameters") if isinstance(participant.get("runtime_parameters"), dict) else {}
        prompt = ""
        for field in self._contract_fields(participant):
            role = str(field.get("input_role") or "").strip()
            name = self._field_name(field)
            if role in {"prompt", "instruction", "query"} and name:
                prompt = self._first_scalar(values.get(name))
                if prompt:
                    break
        if not prompt:
            prompt = self._dependency_material_text(participant, completed_results, dependency_plan)
        if not prompt:
            prompt = self._participant_objective(participant)
        if not str(prompt or "").strip():
            return AgentExecutionResult(
                participant_id=self._participant_identity(participant),
                participant_name=self._participant_name(participant),
                core_run_id=new_id("capability_missing_input"),
                status="requires_input",
                final_answer="",
                workflow_results={"status": "requires_input", "capability_type": "image_generation"},
                pending_action={
                    "kind": "agent_parameter_collection",
                    "message": "Runtime input is required before execution can continue.",
                    "request": {"input_mode": "multi_value_list", "fields": self.parameter_contract_service.to_missing_input_fields(participant)},
                },
                missing_inputs=self.parameter_contract_service.to_missing_input_fields(participant),
                origin="auxiliary_brain",
            )
        payload = await self.image_generation_service.generate(prompt=str(prompt), options={})
        if not payload.get("ok"):
            return AgentExecutionResult(
                participant_id=self._participant_identity(participant),
                participant_name=self._participant_name(participant),
                core_run_id=new_id("image_generation_setup"),
                status=str(payload.get("status") or "failed"),
                final_answer=str(payload.get("message") or "Image generation provider setup is required."),
                workflow_results={"status": payload.get("status") or "failed", "capability_type": "image_generation", "provider_result": payload},
                pending_action={
                    "kind": "capability_provider_setup",
                    "capability_type": "image_generation",
                    "setup_actions": payload.get("setup_actions") or [],
                    "attempted": payload.get("attempted") or [],
                },
                origin="auxiliary_brain",
            )
        material = payload.get("material") if isinstance(payload.get("material"), dict) else {}
        url = str(material.get("download_url") or "")
        name = str(material.get("file_name") or "generated_image")
        final_answer = f"Generated image:\n![{name}]({url})\nDownload: [{name}]({url})" if url else "Generated image material is available."
        return AgentExecutionResult(
            participant_id=self._participant_identity(participant),
            participant_name=self._participant_name(participant),
            core_run_id=str(material.get("download_id") or new_id("image_result")),
            status="completed",
            final_answer=final_answer,
            workflow_results={
                "status": "completed",
                "capability_type": "image_generation",
                "generated_files": [material] if material else [],
                "verified_result_material": material,
                "final_content": final_answer,
            },
            origin="auxiliary_brain",
        )


    async def _execute_video_generation_capability(self, *, participant: dict[str, Any], completed_results: list[Any], dependency_plan: dict[str, Any]) -> AgentExecutionResult | None:
        self._bind_dependency_outputs_to_participant(participant=participant, completed_results=completed_results, dependency_plan=dependency_plan)
        prompt = self._first_scalar(self._value_for_field_role(participant, r"\b(prompt|description|instruction|text|scene|content)\b"))
        if not prompt:
            prompt = self._dependency_material_text(participant, completed_results, dependency_plan)
        if not prompt:
            prompt = self._participant_objective(participant)
        if not str(prompt or "").strip():
            return AgentExecutionResult(
                participant_id=self._participant_identity(participant),
                participant_name=self._participant_name(participant),
                core_run_id=new_id("capability_missing_input"),
                status="requires_input",
                final_answer="",
                workflow_results={"status": "requires_input", "capability_type": "video_generation"},
                pending_action={
                    "kind": "agent_parameter_collection",
                    "message": "Runtime input is required before execution can continue.",
                    "request": {"input_mode": "multi_value_list", "fields": self.parameter_contract_service.to_missing_input_fields(participant)},
                },
                missing_inputs=self.parameter_contract_service.to_missing_input_fields(participant),
                origin="auxiliary_brain",
            )
        payload = await self.video_generation_service.generate(prompt=str(prompt), options={})
        if not payload.get("ok"):
            return AgentExecutionResult(
                participant_id=self._participant_identity(participant),
                participant_name=self._participant_name(participant),
                core_run_id=new_id("video_generation_setup"),
                status=str(payload.get("status") or "failed"),
                final_answer=str(payload.get("message") or "Video generation provider setup is required."),
                workflow_results={"status": payload.get("status") or "failed", "capability_type": "video_generation", "provider_result": payload},
                pending_action=payload.get("interaction_request") or {
                    "kind": "capability_provider_setup",
                    "capability_type": "video_generation",
                    "setup_actions": payload.get("setup_actions") or [],
                    "attempted": payload.get("attempted") or [],
                },
                origin="auxiliary_brain",
            )
        material = payload.get("material") if isinstance(payload.get("material"), dict) else {}
        url = str(material.get("download_url") or "")
        name = str(material.get("file_name") or "generated_video")
        final_answer = f"Generated video:\n[video: {name}]({url})\nDownload: [{name}]({url})" if url else "Generated video material is available."
        return AgentExecutionResult(
            participant_id=self._participant_identity(participant),
            participant_name=self._participant_name(participant),
            core_run_id=str(material.get("download_id") or new_id("video_result")),
            status="completed",
            final_answer=final_answer,
            workflow_results={
                "status": "completed",
                "capability_type": "video_generation",
                "generated_files": [material] if material else [],
                "verified_result_material": material,
                "final_content": final_answer,
            },
            origin="auxiliary_brain",
        )

    def _try_execute_file_material_generation(self, *, participant: dict[str, Any], completed_results: list[Any], dependency_plan: dict[str, Any], task_name: str) -> AgentExecutionResult | None:
        profile = participant.get("capability_profile") if isinstance(participant.get("capability_profile"), dict) else {}
        if not self._looks_like_file_material_contract(participant) and str(profile.get("capability_type") or "") != "file_generation":
            return None
        self._bind_dependency_outputs_to_participant(participant=participant, completed_results=completed_results, dependency_plan=dependency_plan)
        dependency_material = self._dependency_material_text(participant, completed_results, dependency_plan)
        content = dependency_material or self._first_scalar(self._value_for_field_role(participant, r"\b(content|body|text|payload|data|material|input)\b"))
        if not content:
            return None
        name = self._first_scalar(self._value_for_field_role(participant, r"\b(name|filename|file name)\b")) or "generated_output"
        fmt = self._first_scalar(self._value_for_field_role(participant, r"\b(format|type|extension|mime)\b")) or Path(name).suffix.lstrip(".") or "txt"
        filename = self._safe_download_filename(name, fmt)
        download_id = new_id("download")
        target_dir = RUNTIME_DOWNLOADS / download_id
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / filename
        path.write_text(content, encoding="utf-8")
        size = path.stat().st_size
        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        download_url = f"/api/downloads/{download_id}/{filename}"
        file_record = {
            "type": "file",
            "download_id": download_id,
            "file_name": filename,
            "file_path": str(path),
            "download_url": download_url,
            "mime_type": mime_type,
            "size": size,
            "source_material": "verified_upstream_or_runtime_input",
        }
        (target_dir / "metadata.json").write_text(json.dumps(file_record, ensure_ascii=False, indent=2), encoding="utf-8")
        final_answer = f"Generated file: [{filename}]({download_url})"
        return AgentExecutionResult(
            participant_id=self._participant_identity(participant),
            participant_name=self._participant_name(participant),
            core_run_id=download_id,
            status="completed",
            final_answer=final_answer,
            workflow_results={
                "status": "completed",
                "generated_files": [file_record],
                "verified_result_material": {"type": "file", **file_record},
                "final_content": final_answer,
            },
            origin="auxiliary_brain",
        )

    def _generated_files_from_result(self, result: Any) -> list[dict[str, Any]]:
        workflow_results = getattr(result, "workflow_results", None) if result is not None else None
        if not isinstance(workflow_results, dict):
            return []
        files = workflow_results.get("generated_files")
        return [x for x in files if isinstance(x, dict)] if isinstance(files, list) else []

    def _try_return_dependency_material(self, *, participant: dict[str, Any], completed_results: list[Any], dependency_plan: dict[str, Any]) -> AgentExecutionResult | None:
        deps = self._participant_dependency_ids(participant, dependency_plan)
        collected: list[dict[str, Any]] = []
        for result in completed_results:
            result_pid = str(getattr(result, "participant_id", "") or "")
            result_name = str(getattr(result, "participant_name", "") or "")
            if deps and result_pid not in deps and result_name not in deps:
                continue
            collected.extend(self._generated_files_from_result(result))
        if not collected:
            return None
        lines = []
        for item in collected:
            name = str(item.get("file_name") or Path(str(item.get("file_path") or "generated_file")).name)
            url = str(item.get("download_url") or "")
            lines.append(f"Generated file: [{name}]({url})" if url else f"Generated file: {name}")
        return AgentExecutionResult(
            participant_id=self._participant_identity(participant),
            participant_name=self._participant_name(participant),
            core_run_id=new_id("material_return"),
            status="completed",
            final_answer="\n".join(lines),
            workflow_results={
                "status": "completed",
                "generated_files": collected,
                "verified_result_material": {"type": "file_collection", "files": collected},
            },
            origin="auxiliary_brain",
        )

    def _uses_uploaded_artifact_runtime(self, participant: dict[str, Any]) -> bool:
        if not isinstance(participant, dict):
            return False
        artifacts = participant.get("uploaded_artifacts")
        if isinstance(artifacts, list) and artifacts:
            return True
        policy = participant.get("artifact_policy") if isinstance(participant.get("artifact_policy"), dict) else {}
        if policy.get("bind_uploaded_artifacts_to_agent") or str(policy.get("allowed_action") or "") == "use_uploaded_file":
            return True
        text = " ".join(str(participant.get(k) or "") for k in ("instruction", "execution_objective", "definition_instruction", "objective"))
        return bool(re.search(r"\buse\s+file\b|\b[a-zA-Z0-9_.-]+\.[A-Za-z0-9]{1,8}\b", text, flags=re.I))

    def _uses_uploaded_artifact_runtime_for_task(self, participant: dict[str, Any], task_graph: dict[str, Any]) -> bool:
        if self._uses_uploaded_artifact_runtime(participant):
            return True
        artifacts = task_graph.get("uploaded_artifacts") if isinstance(task_graph, dict) else None
        if isinstance(artifacts, list) and artifacts:
            return True
        text = " ".join(str((task_graph or {}).get(k) or "") for k in ("instruction", "task_name", "objective"))
        return bool(re.search(r"\buse\s+file\b|\b[a-zA-Z0-9_.-]+\.[A-Za-z0-9]{1,8}\b", text, flags=re.I))

    def _apply_agent_parameter_values(self, participants: list[dict[str, Any]], provided_inputs: dict[str, Any]) -> None:
        if not isinstance(provided_inputs, dict):
            return
        for participant in participants:
            updated = self.parameter_contract_service.apply_values(participant, provided_inputs)
            pid = str(updated.get("participant_id") or "").strip()
            if pid:
                self.store.write_json(f"generated/agents/{pid}.json", updated)

    def _peer_results_for_participant(self, participant: dict[str, Any], completed_results: list[Any], dependency_plan: dict[str, Any]) -> list[dict[str, Any]]:
        pid = self._participant_identity(participant)
        participant_plan = (dependency_plan.get("participants") or {}).get(pid) or {}
        deps = {str(x) for x in participant_plan.get("depends_on") or [] if str(x)}
        if not deps:
            return []
        safe_results: list[dict[str, Any]] = []
        for result in completed_results:
            result_pid = str(getattr(result, "participant_id", "") or "")
            result_name = str(getattr(result, "participant_name", "") or "")
            if result_pid not in deps and result_name not in deps:
                continue
            safe_results.append(self._safe_peer_result(result))
        return safe_results

    def _safe_peer_result(self, result: Any) -> dict[str, Any]:
        """Return a strict JSON object for dependent-agent context.

        Never use Python repr strings. Keep the summary compact and schema-safe so
        downstream LLM JSON output is not destabilized by quotes, newlines, or
        partially trimmed dictionaries.
        """
        workflow_results = getattr(result, "workflow_results", None) if result is not None else None
        generated_files = []
        if isinstance(workflow_results, dict):
            maybe_files = workflow_results.get("generated_files")
            if isinstance(maybe_files, list):
                generated_files = [x for x in maybe_files if isinstance(x, dict)]
        return {
            "participant_id": str(getattr(result, "participant_id", "") or ""),
            "participant_name": str(getattr(result, "participant_name", "") or ""),
            "status": str(getattr(result, "status", "") or ""),
            "final_answer_summary": self._compact_text(getattr(result, "final_answer", "") or "", 600),
            "generated_files": generated_files,
            "missing_inputs": list(getattr(result, "missing_inputs", None) or []),
        }

    def _compact_text(self, value: Any, max_chars: int = 800) -> str:
        """Return a short, JSON-safe text preview for peer-agent context.

        This is coordination-only data. It must not change the participant's
        own objective; it only gives later participants compact optional context
        from already finished peers.
        """
        if value is None:
            return ""
        text = str(value)
        text = " ".join(text.split())
        if max_chars <= 0:
            return text
        if len(text) <= max_chars:
            return text
        return text[: max_chars - 3].rstrip() + "..."

    def _result_key(self, payload: dict[str, Any]) -> str:
        return str(payload.get("participant_id") or payload.get("participant_name") or "")

    def _dedupe_result_payloads(self, payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Keep the latest result per participant and prefer non-paused results.

        Durable resume first stores a paused result and later replaces it with a
        completed result. This helper prevents stale waiting placeholders from
        being included in final synthesis.
        """
        order: list[str] = []
        merged: dict[str, dict[str, Any]] = {}
        paused_statuses = {"requires_key", "requires_input", "paused"}
        for payload in payloads:
            if not isinstance(payload, dict):
                continue
            key = self._result_key(payload)
            if not key:
                key = str(len(order))
            if key not in merged:
                order.append(key)
                merged[key] = payload
                continue
            old_status = str(merged[key].get("status") or "")
            new_status = str(payload.get("status") or "")
            if old_status in paused_statuses and new_status not in paused_statuses:
                merged[key] = payload
            else:
                merged[key] = payload
        return [merged[key] for key in order if key in merged]

    def _to_agent_results(self, payloads: list[dict[str, Any]]):
        from ai_core.agent_delegation import AgentExecutionResult
        results = []
        paused_statuses = {"requires_key", "requires_input", "paused"}
        for payload in self._dedupe_result_payloads(payloads):
            status = str(payload.get("status") or "")
            if status in paused_statuses:
                continue
            try:
                results.append(AgentExecutionResult(**payload))
            except Exception:
                continue
        return results

    def _clear_waiting_fields(self, run_payload: dict[str, Any]) -> None:
        for key in ["pending_action", "missing_inputs"]:
            run_payload.pop(key, None)

    def _sanitize_result_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return payload
        status = str(payload.get("status") or "")
        if status not in {"requires_key", "requires_input", "paused"}:
            payload.pop("pending_action", None)
            payload["missing_inputs"] = []
        return payload


    def _is_generated_dataflow_step(self, participant: dict[str, Any], task_graph: dict[str, Any]) -> bool:
        pid = self._participant_identity(participant)
        if str(participant.get("workflow_step_type") or "") == "semantic_intermediate_step":
            return True
        for task in task_graph.get("tasks") or []:
            if not isinstance(task, dict):
                continue
            if str(task.get("participant_id") or "") == pid and str(task.get("step_type") or "") == "semantic_intermediate_step":
                return True
        return False


    async def _execute_workflow_step_through_ai_core_with_progress(self, request, progress_callback):
        """Submit a decomposed workflow step back to ai_core.

        The auxiliary brain must not infer the execution method for a step.
        It supplies the clean step objective plus already-resolved public
        dependency material; ai_core performs its normal full pipeline and
        returns a public StepResult.
        """
        try:
            return await self.primary_client.execute_workflow_step_request(
                request,
                progress_callback=progress_callback,
            )
        except AttributeError:
            return await self._execute_agent_request_with_progress(request, progress_callback)
        except TypeError as exc:
            if "progress_callback" not in str(exc):
                raise
            return await self.primary_client.execute_workflow_step_request(request)


    async def _execute_intermediate_step_with_progress(self, request, progress_callback):
        """Execute a generated workflow step as an isolated primary-runtime request.

        Generated/intermediate steps are not participants with durable runtime
        inputs.  They are decomposed user requests.  Therefore this path must
        never fall back to the generic AGENT_REQUEST envelope, because that
        envelope can carry task-level coordination values into ai_core and
        corrupt the step's intent/planning.
        """
        try:
            return await self.primary_client.execute_workflow_step_request(
                request,
                progress_callback=progress_callback,
            )
        except TypeError as exc:
            if "progress_callback" not in str(exc):
                raise
            return await self.primary_client.execute_workflow_step_request(request)

    async def _execute_agent_request_with_progress(self, request, progress_callback):
        try:
            return await self.primary_client.execute_agent_request(
                request,
                progress_callback=progress_callback,
            )
        except TypeError as exc:
            if "progress_callback" not in str(exc):
                raise
            return await self.primary_client.execute_agent_request(request)

    async def _resume_agent_request_with_progress(self, payload, progress_callback, provided_inputs: dict[str, Any] | None = None):
        try:
            return await self.primary_client.resume_agent_request(
                payload,
                progress_callback=progress_callback,
                provided_inputs=provided_inputs,
            )
        except TypeError as exc:
            if "progress_callback" not in str(exc):
                raise
            return await self.primary_client.resume_agent_request(payload, provided_inputs=provided_inputs)

    def _build_primary_runtime_progress_bridge(
        self,
        run_payload: dict[str, Any],
        *,
        participant_index: int,
        participant_name: str,
        resume: bool = False,
    ):
        """Mirror primary-runtime node telemetry into the delegation run.

        The auxiliary layer still does not execute tools or reason over content.
        It only records primary-runtime node status so Agent Studio can show
        whether the primary runtime is parsing, planning, executing, waiting,
        failed, or completed for each delegated participant.
        """

        def bridge(event: dict[str, Any]) -> None:
            mapped = self._map_primary_runtime_event(
                event,
                participant_index=participant_index,
                participant_name=participant_name,
                resume=resume,
            )
            if not mapped:
                return
            self._record_progress(
                run_payload,
                mapped["stage"],
                mapped["label"],
                mapped["status"],
            )
            run_payload.setdefault("primary_runtime_events", []).append({
                "participant_index": participant_index,
                "participant_name": participant_name,
                "core_run_id": event.get("run_id"),
                "event_type": event.get("type"),
                "node_id": event.get("node_id"),
                "status": mapped["status"],
                "label": mapped["label"],
                "at": self._now(),
            })
            self.store.write_json(f"generated/results/{run_payload['run_id']}.json", run_payload)

        return bridge

    def _map_primary_runtime_event(
        self,
        event: dict[str, Any],
        *,
        participant_index: int,
        participant_name: str,
        resume: bool,
    ) -> dict[str, str] | None:
        event_type = str(event.get("type") or "")
        node_id = str(event.get("node_id") or "runtime")
        stage_prefix = f"participant_{participant_index}_ai_core"

        if event_type == "NODE_STARTED":
            return {
                "stage": f"{stage_prefix}_{node_id}",
                "label": f"Primary runtime node started: {node_id}",
                "status": "running",
            }
        if event_type == "NODE_EXECUTING":
            return {
                "stage": f"{stage_prefix}_{node_id}",
                "label": f"Primary runtime executing node: {node_id}",
                "status": "running",
            }
        if event_type == "NODE_RESULT":
            return {
                "stage": f"{stage_prefix}_{node_id}",
                "label": f"Primary runtime node completed: {node_id}",
                "status": "completed",
            }
        if event_type in {"SECRET_REQUIRED", "INTERACTION_REQUEST", "HUMAN_INPUT_REQUIRED"}:
            return {
                "stage": f"{stage_prefix}_{node_id}_waiting_input",
                "label": f"Primary runtime waiting for required input at: {node_id}",
                "status": "waiting",
            }
        if event_type in {"RUN_PAUSED"}:
            return {
                "stage": f"{stage_prefix}_paused",
                "label": "Primary runtime paused and saved checkpoint",
                "status": "waiting",
            }
        if event_type in {"DURABLE_RESUME_STARTED"}:
            return {
                "stage": f"{stage_prefix}_{node_id}_resume",
                "label": f"Primary runtime resumed from checkpoint: {node_id}",
                "status": "running",
            }
        if event_type in {"RUN_FAILED"}:
            return {
                "stage": f"{stage_prefix}_failed",
                "label": "Primary runtime failed",
                "status": "failed",
            }
        if event_type in {"RUN_COMPLETED"}:
            return {
                "stage": f"{stage_prefix}_completed",
                "label": f"Primary runtime completed participant: {participant_name}",
                "status": "completed",
            }
        return None


    def _task_source_material(self, *, task_graph: dict[str, Any], fallback_values: list[Any] | None = None) -> str:
        """Collect original task text for structural binding without capability rules."""
        materials: list[str] = []
        if isinstance(task_graph, dict):
            for key in ("original_instruction", "user_input", "instruction", "objective", "description", "prompt"):
                value = task_graph.get(key)
                if isinstance(value, str) and value.strip():
                    materials.append(value.strip())
            raw = task_graph.get("raw_input")
            if isinstance(raw, dict):
                for key in ("text", "content", "message"):
                    value = raw.get(key)
                    if isinstance(value, str) and value.strip():
                        materials.append(value.strip())
        for value in fallback_values or []:
            if isinstance(value, str) and value.strip():
                materials.append(value.strip())
        out: list[str] = []
        seen: set[str] = set()
        for item in materials:
            key = item.casefold()
            if key not in seen:
                seen.add(key)
                out.append(item)
        return "\n".join(out)

    def _extract_structural_values_from_material(self, material: Any) -> dict[str, list[str]]:
        """Return generic structural values extracted from original user material."""
        text = str(material or "").strip()
        if not text:
            return {}
        try:
            parsed = self.registered_tool_parameter_bridge.entity_extractor.extract(text, source="original_user_material")
            values = parsed.get("values_by_type") if isinstance(parsed, dict) else {}
            return values if isinstance(values, dict) else {}
        except Exception:
            return {}

    def _record_progress(self, run_payload: dict[str, Any], stage: str, label: str, status: str) -> None:
        run_payload["current_stage"] = stage
        run_payload.setdefault("progress_events", []).append({
            "stage": stage,
            "label": label,
            "status": status,
            "at": self._now(),
        })
        self.store.write_json(f"generated/results/{run_payload['run_id']}.json", run_payload)


    def _hydrate_runtime_bindings_for_task(self, task_graph: dict[str, Any], participants: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Recover durable agent capability bindings before a task run.

        Task graphs are allowed to store only step-level structure.  A step may
        therefore contain an empty capability_profile even when the referenced
        durable agent is bound to a runtime capability.  Execution must not let
        that empty step metadata downgrade the agent into generic LLM planning.

        This method is identity/schema driven and capability-agnostic: it only
        restores durable participant fields such as capability_profile,
        execution_policy, and parameter_contract by participant id or stable
        display name.  It does not inspect task names, agent names, tool ids, or
        business vocabulary.
        """
        if not participants:
            return []
        durable_by_id, durable_by_name = self._load_durable_participant_indexes()
        task_step_by_pid: dict[str, dict[str, Any]] = {}
        for step in task_graph.get("tasks") or []:
            if not isinstance(step, dict):
                continue
            pid = str(step.get("participant_id") or step.get("participant") or step.get("agent_id") or "").strip()
            if pid:
                task_step_by_pid.setdefault(pid, step)

        hydrated: list[dict[str, Any]] = []
        for participant in participants:
            if not isinstance(participant, dict):
                continue
            item = copy.deepcopy(participant)
            pid = self._participant_identity(item)
            name = self._participant_name(item).casefold()
            durable = durable_by_id.get(pid) or durable_by_name.get(name) or {}
            step = task_step_by_pid.get(pid) or {}
            item = self._merge_runtime_binding_fields(item, durable)
            item = self._merge_runtime_binding_fields(item, step)
            hydrated.append(item)
        return hydrated

    def _load_durable_participant_indexes(self) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        by_id: dict[str, dict[str, Any]] = {}
        by_name: dict[str, dict[str, Any]] = {}
        try:
            records = self.store.list_json("generated/agents")
        except Exception:
            records = []
        for record in records or []:
            if not isinstance(record, dict):
                continue
            pid = self._participant_identity(record)
            if pid:
                by_id[pid] = record
            name = self._participant_name(record).casefold()
            if name:
                existing = by_name.get(name)
                if existing is None or str(record.get("created_at") or "") >= str(existing.get("created_at") or ""):
                    by_name[name] = record
        return by_id, by_name

    def _merge_runtime_binding_fields(self, participant: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(source, dict) or not source:
            return participant
        out = participant

        source_profile = source.get("capability_profile") if isinstance(source.get("capability_profile"), dict) else {}
        current_profile = out.get("capability_profile") if isinstance(out.get("capability_profile"), dict) else {}
        if source_profile and (not current_profile or not str(current_profile.get("capability_type") or current_profile.get("tool_id") or "").strip()):
            out["capability_profile"] = copy.deepcopy(source_profile)

        source_policy = str(source.get("execution_policy") or "").strip()
        current_policy = str(out.get("execution_policy") or "").strip()
        if source_policy and (not current_policy or current_policy == "delegate_to_ai_core"):
            if source_policy != "delegate_to_ai_core" or not current_policy:
                out["execution_policy"] = source_policy

        source_contract = source.get("parameter_contract") if isinstance(source.get("parameter_contract"), dict) else {}
        current_contract = out.get("parameter_contract") if isinstance(out.get("parameter_contract"), dict) else {}
        source_params = source_contract.get("parameters") if isinstance(source_contract.get("parameters"), list) else []
        current_params = current_contract.get("parameters") if isinstance(current_contract.get("parameters"), list) else []
        if source_contract and source_params and not current_params:
            out["parameter_contract"] = copy.deepcopy(source_contract)
            out["missing_information"] = copy.deepcopy(source_contract.get("missing_information") or [])

        for key in (
            "input_contract",
            "output_contract",
            "depends_on",
            "input_from",
            "workflow_step_type",
            "source_step_id",
            "step_id",
            "compiled_step_id",
            "execution_contract",
            "source_contract",
            "presentation_contract",
            "binding_contract",
            "execution_known",
            "semantic_known",
            "task_metadata",
            "prompt_profile",
        ):
            value = source.get(key)
            if value not in (None, "", [], {}) and out.get(key) in (None, "", [], {}):
                out[key] = copy.deepcopy(value)
        return out

    def _fresh_task_participants(self, participants: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return task-run copies with no persisted runtime values.

        Agent definitions are durable capability/schema records. Parameter values
        belong to one task run only. This prevents a later task execution from
        silently reusing values collected during an earlier run.
        """
        fresh: list[dict[str, Any]] = []
        for participant in participants:
            item = copy.deepcopy(participant)
            item["runtime_parameters"] = {}
            contract = item.get("parameter_contract") if isinstance(item.get("parameter_contract"), dict) else {}
            params = contract.get("parameters") if isinstance(contract.get("parameters"), list) else []
            for param in params:
                if isinstance(param, dict):
                    param["values"] = []
            if self._uses_uploaded_artifact_runtime(item):
                contract = {"contract_type": "task_runtime_parameter_contract", "parameters": [], "missing_information": [], "runtime_scope": "task_run"}
                item["parameter_contract"] = contract
                item["missing_information"] = []
            elif isinstance(contract, dict):
                contract["missing_information"] = self.parameter_contract_service.missing_parameters({"parameter_contract": contract, "runtime_parameters": {}})
                item["parameter_contract"] = contract
                item["missing_information"] = item.get("parameter_contract", {}).get("missing_information", []) if isinstance(item.get("parameter_contract"), dict) else []
            else:
                item["missing_information"] = []
            fresh.append(item)
        return fresh

    def _select_participants(self, task_graph: dict[str, Any], participants: list[dict[str, Any]]) -> list[dict[str, Any]]:
        declared_ids = {str(x).strip() for x in (task_graph.get("selected_participant_ids") or []) if str(x).strip()}
        if declared_ids:
            selected = [
                participant
                for participant in (participants or [])
                if str(participant.get("participant_id") or participant.get("id") or "").strip() in declared_ids
            ]
            found_ids = {str(participant.get("participant_id") or participant.get("id") or "").strip() for participant in selected}
            missing_ids = declared_ids - found_ids
            if missing_ids:
                selected.extend(self._participants_from_task_graph(task_graph, missing_ids))
            # A task graph with selected ids must never fall back to unrelated
            # durable participants.  Missing generated steps are rebuilt from
            # the task graph, otherwise execution stays empty and fails cleanly.
            return self._dedupe_participants_for_execution(selected)
        if not participants:
            return []
        text = (str(task_graph.get("instruction") or "") + " " + str(task_graph.get("task_name") or "")).casefold()
        selected = []
        for participant in participants:
            name = str(participant.get("name") or participant.get("agent_name") or "").casefold()
            pid = str(participant.get("participant_id") or participant.get("id") or "").casefold()
            if name and name in text:
                selected.append(participant)
            elif pid and pid in text:
                selected.append(participant)
        return self._dedupe_participants_for_execution(selected or participants)

    def _participants_from_task_graph(self, task_graph: dict[str, Any], participant_ids: set[str]) -> list[dict[str, Any]]:
        rebuilt: list[dict[str, Any]] = []
        seen: set[str] = set()
        for task in task_graph.get("tasks") or []:
            if not isinstance(task, dict):
                continue
            pid = str(task.get("participant_id") or "").strip()
            if not pid or pid not in participant_ids or pid in seen:
                continue
            seen.add(pid)
            name = str(task.get("participant_display_name") or task.get("source_instruction_fragment") or pid).strip() or pid
            objective = str(task.get("source_instruction_fragment") or task.get("objective") or name).strip()
            rebuilt.append({
                "participant_id": pid,
                "name": name,
                "agent_name": name,
                "display_name": name,
                "role_name": name,
                "instruction": objective,
                "execution_objective": objective,
                "definition_instruction": objective,
                "parameter_contract": task.get("parameter_contract") if isinstance(task.get("parameter_contract"), dict) else {
                    "contract_type": "generated_intermediate_step_contract",
                    "parameters": [],
                    "missing_information": [],
                    "runtime_scope": "task_run",
                },
                "capability_profile": task.get("capability_profile") if isinstance(task.get("capability_profile"), dict) else {},
                "runtime_parameters": {},
                "missing_information": [],
                "origin": "auxiliary_brain",
                "status": "created",
                "execution_policy": "delegate_to_ai_core",
                "generated_by": "task_graph_rebuild",
                "depends_on": task.get("depends_on") or [],
                "input_from": task.get("input_from") or task.get("depends_on") or [],
                "workflow_step_type": task.get("step_type") or "semantic_intermediate_step",
                "source_step_id": task.get("source_step_id") or "",
                "input_contract": task.get("input_contract") if isinstance(task.get("input_contract"), dict) else {},
                "output_contract": task.get("output_contract") if isinstance(task.get("output_contract"), dict) else {},
            })
        return rebuilt

    def _dedupe_participants_for_execution(self, participants: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Keep one participant per reusable capability identity.

        Duplicate agent profiles can appear after repeated create-agent commands.
        Execution should not run identical participants twice for one task. This
        uses generic identity fields only and prefers the most recently created
        profile so the latest parameter contract/artifact binding wins.
        """
        chosen: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for participant in participants:
            if not isinstance(participant, dict):
                continue
            key = self._participant_reuse_key(participant)
            if not key:
                key = str(participant.get("participant_id") or participant.get("id") or len(order))
            existing = chosen.get(key)
            if existing is None:
                chosen[key] = participant
                order.append(key)
                continue
            if str(participant.get("created_at") or "") >= str(existing.get("created_at") or ""):
                chosen[key] = participant
        return [chosen[k] for k in order if k in chosen]

    def _participant_reuse_key(self, participant: dict[str, Any]) -> str:
        name = str(participant.get("name") or participant.get("agent_name") or participant.get("display_name") or "").strip().casefold()
        objective = str(participant.get("execution_objective") or participant.get("instruction") or "").strip().casefold()
        objective = re.sub(r"\s+", " ", objective)[:180]
        artifacts = participant.get("uploaded_artifacts") if isinstance(participant.get("uploaded_artifacts"), list) else []
        artifact_sig = ",".join(sorted(str(a.get("artifact_id") or a.get("path") or a.get("filename") or "") for a in artifacts if isinstance(a, dict)))
        return "|".join(part for part in (name, objective, artifact_sig) if part)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
