from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import copy
import json
import re
import hashlib

from auxiliary_brain.delegation import AgentDelegationRuntime
from auxiliary_brain.runtime import new_id
from auxiliary_brain.storage import JsonStore
from auxiliary_brain.studio.command_router import StudioCommandRouter
from ai_core.runtime.adaptation import FeedbackClassifier, ModelUpgradeController, RerunStrategy
from ai_core.interaction.natural_conversation import NaturalConversationService
from ai_core.tools.runtime_registered_tool_service import RuntimeRegisteredToolService
from ai_core.runtime.modeling.model_runtime_preflight import ModelRuntimePreflight
from auxiliary_brain.parameters.agent_parameter_contract import AgentParameterContractService
from ai_core.artifacts.artifact_registry import UploadedArtifactRegistry
from ai_core.artifacts.uploaded_artifact_contract import UploadedArtifactContractBuilder
from ai_core.artifacts.artifact_edit_service import ArtifactEditService
from ai_core.commands import CommandSetService
from ai_core.capabilities.capability_dispatcher import CapabilityDispatcher
from ai_core.media import ImageGenerationService, VideoGenerationService
from ai_core.media.video_generation_setup_wizard import VideoGenerationSetupWizard
from ai_core.context.execution_reuse_store import ExecutionReuseStore
from ai_core.execution.parameter_resolution import ParameterResolutionPipeline, PreflightResolutionContext
from auxiliary_brain.studio.instruction_workflow_planner import InstructionWorkflowPlanner
from auxiliary_brain.studio.runtime_semantic_planner import RuntimeSemanticPlanner
from ai_core.runtime.capability.registered_tool_agent_binder import RegisteredToolAgentBinder
from verification_brain import RuntimeVerificationFoundation
from presentation_brain import FailureMessageRenderer, PresentationProfileRegistry
from ai_core.runtime.state import runtime_state_manager
from ai_core.runtime.services import runtime_service_manager


class AgentStudioService:
    """Studio service for managing participants, task graphs, and delegation state."""

    def __init__(self, store: JsonStore | None = None, router: StudioCommandRouter | None = None) -> None:
        self.store = store or JsonStore()
        self.router = router or StudioCommandRouter()
        self.delegation_runtime = AgentDelegationRuntime(store=self.store)
        self.feedback_classifier = FeedbackClassifier()
        self.model_upgrade_controller = ModelUpgradeController()
        self.rerun_strategy = RerunStrategy()
        self.natural_conversation = NaturalConversationService()
        self.model_preflight = ModelRuntimePreflight()
        self.parameter_contract_service = AgentParameterContractService()
        self.artifact_registry = UploadedArtifactRegistry()
        self.uploaded_artifact_contract = UploadedArtifactContractBuilder()
        self.artifact_edit_service = ArtifactEditService()
        self.command_set_service = CommandSetService()
        self.execution_reuse_store = ExecutionReuseStore()
        self.parameter_resolution_pipeline = ParameterResolutionPipeline()
        self.instruction_workflow_planner = InstructionWorkflowPlanner()
        self.runtime_semantic_planner = RuntimeSemanticPlanner()
        self.registered_tool_service = RuntimeRegisteredToolService()
        self.registered_tool_agent_binder = RegisteredToolAgentBinder()
        self.verification_foundation = RuntimeVerificationFoundation()
        self.failure_message_renderer = FailureMessageRenderer()
        self.direct_capability_dispatcher = CapabilityDispatcher(handlers={
            "image_generation": self._handle_direct_image_generation,
            "video_generation": self._handle_direct_video_generation,
        })
        self.store.ensure_workspace()
        self.community_id = self._ensure_community()

    async def handle_message(self, message: str, provided_inputs: dict[str, Any] | None = None, uploaded_artifacts: list[dict[str, Any]] | None = None, session_id: str | None = None, presentation_profile: str | None = None) -> dict[str, Any]:
        state_run_id = str((provided_inputs or {}).get("_runtime_state_run_id") or (provided_inputs or {}).get("_state_run_id") or "studio_runtime")
        runtime_state_manager.emit(
            run_id=state_run_id,
            step_id="intent.route",
            level="user",
            kind="method",
            status="running",
            title="Intent and command routing",
            message="Classifying the request into a generic runtime action.",
            method="studio_command_router",
            progress=10,
        )
        direct = self._direct_ephemeral_answer(message)
        if direct is not None:
            self.execution_reuse_store.save_short_answer(query=message, answer=direct, source="ephemeral_direct")
            return {
                "action": "ephemeral_chat",
                "origin": "auxiliary_brain",
                "status": "completed",
                "final_answer": direct,
                "memory_saved": False,
                "context_trace": {"short_answer_cache": False, "llm_used": False, "planning_used": False},
            }
        routed = self.router.route(message)
        runtime_state_manager.emit(
            run_id=state_run_id,
            step_id="intent.route",
            level="developer",
            kind="output",
            status="completed",
            title="Routing completed",
            message=f"Selected action: {routed.action}",
            output={"action": routed.action, "name": routed.name},
            progress=100,
        )
        if routed.action == "list_command_set":
            return self.list_command_set()
        if routed.action == "update_command_set":
            return self.update_command_set(message)
        if routed.action == "create_participant":
            return await self.create_participant(message, routed.name, uploaded_artifacts=uploaded_artifacts)
        if routed.action == "create_task":
            return self.create_task_graph(message, routed.name, uploaded_artifacts=uploaded_artifacts, presentation_profile=presentation_profile)
        if routed.action == "create_runtime_service":
            return self.create_runtime_service(message, routed.name)
        if routed.action == "start_runtime_service":
            return self.start_runtime_service(routed.name or self._extract_runtime_service_name(message))
        if routed.action == "stop_runtime_service":
            return self.stop_runtime_service(routed.name or self._extract_runtime_service_name(message))
        if routed.action == "list_runtime_services":
            return self.list_runtime_services()

        # Direct output-modality requests must be isolated from ordinary chat and
        # from text-model preflight.  If a provider is missing, the user should
        # see a capability setup/status result, not the generic chat fallback.
        if routed.action == "chat":
            direct_capability = await self.direct_capability_dispatcher.dispatch(
                text=message,
                context={
                    "session_id": session_id,
                    "surface": "agent_studio",
                    "provided_inputs": provided_inputs or {},
                },
            )
            if direct_capability is not None:
                return direct_capability

        short_cached = self.execution_reuse_store.get_short_answer(message)
        if short_cached:
            return {
                "action": "short_answer_cache",
                "origin": "auxiliary_brain",
                "status": "completed",
                "final_answer": short_cached.get("answer"),
                "memory_saved": False,
                "context_trace": {"short_answer_cache": True, "llm_used": False, "planning_used": False},
            }

        # Requests that need the generic ai_core conversation/capability-acquisition
        # pipeline must not be intercepted by direct participant invocation.
        # This keeps durable Agent execution separate from runtime capability
        # acquisition / external evidence / repair-style flows.
        core_pipeline_requested = self.natural_conversation.needs_core_conversation_pipeline(message)

        # If the message is exactly a known task name, treat it as an execution
        # request. This keeps the UI natural: users can type `taskC` after
        # creating it, without falling into ordinary chat or re-planning.
        bare_task_name = self._resolve_bare_task_name(message)
        if routed.action == "chat" and bare_task_name:
            return await self.execute_task(bare_task_name, provided_inputs=provided_inputs, instruction=message)

        if routed.action == "chat":
            direct_agent_response = await self._maybe_execute_direct_participant_invocation(
                message,
                provided_inputs=provided_inputs,
                uploaded_artifacts=uploaded_artifacts,
            )
            if direct_agent_response is not None:
                return direct_agent_response

        # Model-dependent paths must not enter the runtime if the selected
        # provider mode is impossible to satisfy. This prevents confusing late
        # failures such as input_parsing failing with "No real LLM provider is
        # available" after the user selected Local only while no local service
        # is running. The preflight is model-provider only and contains no
        # business-domain logic.
        preflight = await self.model_preflight.check_before_runtime()
        if not preflight.get("ok"):
            return preflight

        if routed.action == "execute_task":
            return await self.execute_task(routed.name, provided_inputs=provided_inputs, instruction=message)

        # Capability-gap / external-evidence requests can contain negative
        # wording such as "does not have", "missing", or "cannot handle".
        # Those words must not be treated as feedback about a previous run.
        # Give the generic ai_core conversation pipeline priority so it can
        # perform input_parsing -> intent_recognition -> workflow_planning ->
        # web_retrieval -> result_verification -> final_synthesis.
        if routed.action == "feedback_adaptation" and core_pipeline_requested:
            return await self.natural_conversation.reply(message, latest_task=self._latest_task_name(), session_id=session_id, runtime_state_run_id=state_run_id)

        if routed.action == "feedback_adaptation":
            return await self.handle_feedback(message, routed.name)
        artifact_edit = await self._maybe_handle_artifact_edit_message(message, uploaded_artifacts=uploaded_artifacts)
        if artifact_edit is not None:
            return artifact_edit
        if not core_pipeline_requested:
            feedback = self.feedback_classifier.classify(message, fallback_target=self._latest_task_name())
            if feedback.get("matched"):
                return await self.handle_feedback(message, feedback.get("target_task"))
        return await self.natural_conversation.reply(message, latest_task=self._latest_task_name(), session_id=session_id, runtime_state_run_id=state_run_id)


    async def _handle_direct_image_generation(self, request: dict[str, Any]) -> dict[str, Any]:
        text = str(request.get("text") or "").strip()
        service = ImageGenerationService()
        provider_payload = await service.generate(prompt=text, options={})
        status = str(provider_payload.get("status") or ("completed" if provider_payload.get("ok") else "failed"))
        if not provider_payload.get("ok"):
            return {
                "status": status,
                "final_answer": str(provider_payload.get("message") or "Image generation provider setup is required."),
                "pending_action": {
                    "kind": "capability_provider_setup",
                    "capability_type": "image_generation",
                    "setup_actions": provider_payload.get("setup_actions") or [],
                    "attempted": provider_payload.get("attempted") or [],
                },
                "workflow_results": {
                    "status": status,
                    "capability_type": "image_generation",
                    "provider_result": provider_payload,
                },
            }
        material = provider_payload.get("material") if isinstance(provider_payload.get("material"), dict) else {}
        url = str(material.get("download_url") or "").strip()
        name = str(material.get("file_name") or "generated_image").strip() or "generated_image"
        final_answer = f"Generated image:\n![{name}]({url})\nDownload: [{name}]({url})" if url else "Generated image material is available."
        return {
            "status": "completed",
            "final_answer": final_answer,
            "workflow_results": {
                "status": "completed",
                "capability_type": "image_generation",
                "generated_files": [material] if material else [],
                "verified_result_material": material,
                "provider_result": provider_payload,
                "final_content": final_answer,
            },
        }


    async def _handle_direct_video_generation(self, request: dict[str, Any]) -> dict[str, Any]:
        text = str(request.get("text") or "").strip()
        provided_inputs = request.get("provided_inputs") if isinstance(request.get("provided_inputs"), dict) else {}
        setup_result = None
        if provided_inputs:
            setup_result = VideoGenerationSetupWizard().apply_inputs(provided_inputs)
        service = VideoGenerationService()
        provider_payload = await service.generate(prompt=text, options={})
        if setup_result:
            provider_payload = dict(provider_payload)
            provider_payload["runtime_setup"] = setup_result
        status = str(provider_payload.get("status") or ("completed" if provider_payload.get("ok") else "failed"))
        if not provider_payload.get("ok"):
            return {
                "status": status,
                "final_answer": str(provider_payload.get("message") or "Video generation provider setup is required."),
                "pending_action": provider_payload.get("interaction_request") or {
                    "kind": "capability_provider_setup",
                    "capability_type": "video_generation",
                    "setup_actions": provider_payload.get("setup_actions") or [],
                    "attempted": provider_payload.get("attempted") or [],
                },
                "workflow_results": {
                    "status": status,
                    "capability_type": "video_generation",
                    "provider_result": provider_payload,
                },
            }
        material = provider_payload.get("material") if isinstance(provider_payload.get("material"), dict) else {}
        url = str(material.get("download_url") or "").strip()
        name = str(material.get("file_name") or "generated_video").strip() or "generated_video"
        final_answer = f"Generated video:\n[video: {name}]({url})\nDownload: [{name}]({url})" if url else "Generated video material is available."
        return {
            "status": "completed",
            "final_answer": final_answer,
            "workflow_results": {
                "status": "completed",
                "capability_type": "video_generation",
                "generated_files": [material] if material else [],
                "verified_result_material": material,
                "provider_result": provider_payload,
                "final_content": final_answer,
            },
        }

    def _direct_ephemeral_answer(self, message: str) -> str | None:
        # No fixed phrase list is used here.  Ordinary conversation is routed by
        # the command router as chat and answered by NaturalConversationService
        # outside task/graph execution.  This hook remains only for future
        # deployment-provided deterministic policies.
        return None

    def _compact_final_answer(self, value: Any) -> str:
        return self.execution_reuse_store.compact_final_answer(str(value or ""))

    async def _try_reused_task_execution(
        self,
        task_name: str,
        task_graph: dict[str, Any],
        participants: list[dict[str, Any]],
        runtime_parameters: dict[str, Any],
    ) -> dict[str, Any] | None:
        decision = self.execution_reuse_store.decide(task_name, runtime_parameters)
        if decision.reason == "no_reusable_asset":
            return None
        if self._should_bypass_stale_reuse_asset(decision.asset, task_graph, participants, runtime_parameters):
            return None
        if decision.reason == "missing_runtime_inputs":
            run_id = new_id("delegation_run")
            fields = decision.missing_inputs or []
            payload = {
                "run_id": run_id,
                "origin": "auxiliary_brain",
                "status": "requires_input",
                "task_name": task_name,
                "current_stage": "waiting_for_reused_asset_parameters",
                "pending_action": {"kind": "runtime_parameter_input", "source": "execution_reuse_asset"},
                "missing_inputs": fields,
                "runtime_parameters": runtime_parameters,
                "completed_at": self._now(),
                "context_trace": {
                    "task_registry": True,
                    "agent_registry": True,
                    "artifact_registry": bool((decision.asset or {}).get("artifact_paths")),
                    "planning_used": False,
                    "llm_used": False,
                    "reuse_asset_id": (decision.asset or {}).get("asset_id"),
                },
            }
            self.store.write_json(f"generated/results/{run_id}.json", payload)
            return {
                "action": "execute_task_graph",
                "origin": "auxiliary_brain",
                "status": "requires_input",
                "task_name": task_name,
                "run_id": run_id,
                "pending_action": payload["pending_action"],
                "missing_inputs": fields,
                "interaction_request": {
                    "type": "collect_runtime_parameters",
                    "kind": "runtime_parameter_input",
                    "fields": fields,
                    "message": self._paused_message(fields, payload["pending_action"]),
                },
                "message": self._paused_message(fields, payload["pending_action"]),
                "context_trace": payload["context_trace"],
            }
        if decision.reusable and decision.asset:
            reused = await self.execution_reuse_store.execute_reused_asset(asset=decision.asset, provided_inputs=runtime_parameters)
            if reused.get("status") == "completed":
                run_id = new_id("delegation_run")
                final_answer = self._compact_final_answer(reused.get("final_answer") or "Reused execution completed.")
                payload = {
                    "run_id": run_id,
                    "origin": "auxiliary_brain",
                    "status": "completed",
                    "task_name": task_name,
                    "current_stage": "completed",
                    "synthesis": {"status": "completed", "final_answer": final_answer},
                    "reuse_execution": reused,
                    "completed_at": self._now(),
                    "context_trace": reused.get("context_trace"),
                }
                self.store.write_json(f"generated/results/{run_id}.json", payload)
                return {
                    "action": "execute_task_graph",
                    "origin": "auxiliary_brain",
                    "status": "completed",
                    "task_name": task_name,
                    "run_id": run_id,
                    "final_answer": final_answer,
                    "context_trace": reused.get("context_trace"),
                }
            # A direct reuse asset was selected and execution was attempted.
            # Do not silently fall back to full planning on execution failure,
            # because that hides reusable-asset defects and makes repeated runs
            # look like first-time executions.  Return the failure with trace so
            # the repair layer or user feedback can fix the reusable asset.
            run_id = new_id("delegation_run")
            final_answer = self._compact_final_answer(reused.get("final_answer") or reused.get("stderr") or reused.get("reason") or "Reusable execution failed.")
            payload = {
                "run_id": run_id,
                "origin": "auxiliary_brain",
                "status": "failed",
                "task_name": task_name,
                "current_stage": "reuse_execution_failed",
                "synthesis": {"status": "failed", "final_answer": final_answer},
                "reuse_execution": reused,
                "completed_at": self._now(),
                "context_trace": reused.get("context_trace"),
            }
            self.store.write_json(f"generated/results/{run_id}.json", payload)
            return {
                "action": "execute_task_graph",
                "origin": "auxiliary_brain",
                "status": "failed",
                "task_name": task_name,
                "run_id": run_id,
                "final_answer": final_answer,
                "context_trace": reused.get("context_trace"),
            }
        return None

    def _should_bypass_stale_reuse_asset(
        self,
        asset: dict[str, Any] | None,
        task_graph: dict[str, Any],
        participants: list[dict[str, Any]],
        runtime_parameters: dict[str, Any],
    ) -> bool:
        if not isinstance(asset, dict):
            return False
        schema = asset.get("parameter_schema") if isinstance(asset.get("parameter_schema"), list) else []
        required_fields = {str(item.get("field") or item.get("name") or "").strip() for item in schema if isinstance(item, dict) and item.get("required")}
        if required_fields != {"payload"}:
            return False
        has_registered_tool = False
        for participant in participants:
            profile = participant.get("capability_profile") if isinstance(participant.get("capability_profile"), dict) else {}
            if str(profile.get("capability_type") or "") == "runtime_registered_tool":
                has_registered_tool = True
                break
        if not has_registered_tool:
            for step in task_graph.get("tasks") if isinstance(task_graph.get("tasks"), list) else []:
                if not isinstance(step, dict):
                    continue
                profile = step.get("capability_profile") if isinstance(step.get("capability_profile"), dict) else {}
                if str(profile.get("capability_type") or "") == "runtime_registered_tool":
                    has_registered_tool = True
                    break
        if not has_registered_tool:
            return False
        return any(str(key).strip() and str(key).strip() != "payload" for key in runtime_parameters.keys())

    def _resolve_bare_task_name(self, message: str) -> str | None:
        text = str(message or "").strip().strip(" .,:;\"'")
        if not text or len(text.split()) != 1:
            return None
        resolved = self._resolve_task_name(text)
        if resolved:
            return resolved
        # Be tolerant of case-only differences in the visible task name.
        lowered = text.casefold()
        for graph in self.store.list_json("generated/tasks"):
            name = str(graph.get("task_name") or graph.get("graph_id") or "").strip()
            if name and name.casefold() == lowered:
                return name
        return None

    def list_command_set(self) -> dict[str, Any]:
        payload = self.command_set_service.list_commands()
        payload.update({
            "action": "list_command_set",
            "origin": "ai_core",
            "message": "Default and runtime-customized command set is listed.",
        })
        return payload

    def update_command_set(self, message: str) -> dict[str, Any]:
        result = self.command_set_service.update_from_instruction(message)
        # Refresh router cache so the new phrases work immediately at runtime.
        try:
            self.router.reload()
        except Exception:
            pass
        result.update({
            "action": "update_command_set",
            "origin": "ai_core",
        })
        return result


    async def _maybe_handle_artifact_edit_message(self, message: str, uploaded_artifacts: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
        """Create a reviewable edit proposal for an uploaded artifact when the
        user asks to change or regenerate a file.

        This is a generic artifact-edit bridge for Agent Studio.  It only
        decides whether the current user message is an artifact edit request and
        resolves the referenced uploaded artifact.  The actual modification is
        delegated to ArtifactEditService, which creates a draft file and waits
        for user confirmation before replacing the original.
        """
        text = str(message or "").strip()
        if not text:
            return None
        if not self._looks_like_artifact_edit_request(text):
            return None

        refs = self._resolve_uploaded_artifacts_for_instruction(text, uploaded_artifacts)
        if not refs:
            registry_items = self.artifact_registry.list()
            if len(registry_items) == 1:
                refs = [registry_items[0]]
        if not refs:
            return {
                "action": "artifact_edit_request",
                "origin": "auxiliary_brain",
                "status": "requires_input",
                "message": "Please upload or select the file to modify before requesting a file edit.",
                "interaction_request": {
                    "type": "select_uploaded_artifact",
                    "kind": "artifact_selection",
                    "fields": [{
                        "field": "artifact_id",
                        "label": "Uploaded file",
                        "input_type": "artifact_selector",
                        "required": True,
                        "description": "Select the uploaded artifact to modify.",
                    }],
                },
            }

        artifact = refs[0]
        artifact_id = str(artifact.get("artifact_id") or artifact.get("id") or "").strip()
        if not artifact_id:
            return {
                "action": "artifact_edit_request",
                "origin": "auxiliary_brain",
                "status": "blocked",
                "message": "The selected artifact does not have a resolvable artifact_id.",
                "uploaded_artifacts": refs,
            }

        proposal = await self.artifact_edit_service.propose_edit(
            artifact_id=artifact_id,
            instruction=text,
        )
        if not proposal.get("ok"):
            return {
                "action": "artifact_edit_proposal",
                "origin": "auxiliary_brain",
                "status": proposal.get("status", "failed"),
                "message": proposal.get("message") or "Could not create an artifact edit proposal.",
                "proposal": proposal.get("proposal"),
                "uploaded_artifacts": refs,
            }
        return {
            "action": "artifact_edit_proposal",
            "origin": "auxiliary_brain",
            "status": "pending_review",
            "message": "A modified draft file was generated. Review it, download it, provide feedback for another revision, confirm replacement, or cancel.",
            "artifact": artifact,
            "proposal": proposal.get("proposal"),
            "preview": proposal.get("preview"),
            "interaction_request": {
                "type": "review_artifact_edit_proposal",
                "kind": "artifact_edit_review",
                "proposal": proposal.get("proposal"),
                "preview": proposal.get("preview"),
                "actions": ["download", "revise", "confirm", "cancel"],
            },
        }

    def _looks_like_artifact_edit_request(self, message: str) -> bool:
        """Generic command-shape detection for file modification requests.

        The detector is intentionally not domain-specific.  It looks for a file
        reference plus an edit/regeneration verb, or a direct instruction that
        says to generate a new file/code file from an uploaded file.
        """
        text = str(message or "")
        lowered = text.casefold()
        # Runtime capability acquisition is handled by ai_core.  It must not be
        # routed into artifact edit just because the request contains words like
        # generate/build/create or a previous uploaded artifact exists.
        if any(marker in lowered for marker in (
            "acquire runtime capability",
            "runtime capability acquisition",
            "acquire capability",
            "capability acquisition",
        )):
            return False
        file_ref = bool(re.search(r"\b[\w .()\-]+\.[A-Za-z0-9]{1,12}\b", text))
        edit_words = (
            "change", "modify", "update", "edit", "rewrite", "refactor", "convert", "replace", "regenerate",
            "generate a new", "generate new", "new code file", "new file", "修改", "更改", "更新", "编辑", "生成新", "重新生成",
        )
        file_words = ("file", "code file", "uploaded", "artifact", "文件", "代码")
        has_edit = any(word in lowered for word in edit_words)
        has_file_word = any(word in lowered for word in file_words)
        return bool(has_edit and (file_ref or has_file_word))

    async def handle_feedback(self, message: str, task_name: str | None = None) -> dict[str, Any]:
        feedback = self.feedback_classifier.classify(message, fallback_target=task_name or self._latest_task_name())
        target_task = self._resolve_task_name(str(feedback.get("target_task") or task_name or self._latest_task_name() or "").strip()) or ""
        self.model_upgrade_controller.record_upgrade_request(
            target_node=str(feedback.get("target_node") or "output"),
            reason=str(feedback.get("intent") or "studio_feedback"),
            message=message,
        )
        if not target_task:
            return {
                "action": "runtime_feedback",
                "origin": "auxiliary_brain",
                "status": "recorded",
                "message": "Feedback was recorded, but no previous task was found for re-optimization.",
                "feedback": feedback,
            }
        task_graph = self.store.read_json(f"generated/tasks/{target_task}.json")
        if not task_graph:
            runtime_state_manager.emit(run_id=state_run_id, step_id="task.load", level="developer", kind="validation", status="failed", title="Task graph not found", message="The requested task graph was not found.", output={"task_name": task_name}, progress=100)
            return {
                "action": "runtime_feedback",
                "origin": "auxiliary_brain",
                "status": "not_found",
                "task_name": target_task,
                "message": "Feedback was recorded, but the target task graph was not found.",
                "feedback": feedback,
            }
        latest_run = self._latest_run_for_task(target_task)
        if not latest_run:
            repair_candidate = self.execution_reuse_store.record_repair_candidate(
                task_name=target_task,
                feedback=message,
                run_payload={},
            )
            return {
                "action": "runtime_feedback",
                "origin": "auxiliary_brain",
                "status": "recorded",
                "task_name": target_task,
                "message": "Feedback was recorded as a self-repair candidate, but no previous run result was found to re-optimize.",
                "feedback": feedback,
                "repair_candidate": repair_candidate,
            }
        repair_candidate = self.execution_reuse_store.record_repair_candidate(
            task_name=target_task,
            feedback=message,
            run_payload=latest_run,
        )
        strategy = self.rerun_strategy.choose(feedback=feedback, run_payload=latest_run)
        if strategy.get("strategy") != "node_level_resynthesis":
            return {
                "action": "runtime_feedback",
                "origin": "auxiliary_brain",
                "status": "recorded",
                "task_name": target_task,
                "message": "Feedback was recorded as a self-repair candidate.",
                "feedback": feedback,
                "strategy": strategy,
                "repair_candidate": repair_candidate,
            }
        result = await self.delegation_runtime.reoptimize_result(
            run_payload=latest_run,
            task_graph=task_graph,
            feedback=feedback,
            strategy=strategy,
        )
        synthesis = result.get("synthesis") if isinstance(result.get("synthesis"), dict) else {}
        return {
            "action": "runtime_feedback",
            "origin": "auxiliary_brain",
            "status": result.get("status", "completed"),
            "task_name": target_task,
            "run_id": result.get("run_id"),
            "message": "Feedback was applied and the result was re-optimized with model escalation.",
            "feedback": feedback,
            "strategy": strategy,
            "repair_candidate": repair_candidate,
            "final_answer": self._compact_final_answer(synthesis.get("final_answer")),
            "delivery": result.get("delivery"),
        }

    def _latest_task_name(self) -> str | None:
        runs = self.store.list_json("generated/results")
        if not runs:
            return None
        runs.sort(key=lambda item: str(item.get("completed_at") or item.get("started_at") or ""), reverse=True)
        return str(runs[0].get("task_name") or "").strip() or None

    def _resolve_task_name(self, task_name: str | None) -> str | None:
        candidate = str(task_name or "").strip()
        tasks = self.store.list_json("generated/tasks")
        names = [str(t.get("task_name") or t.get("graph_id") or "").strip() for t in tasks]
        names = [n for n in names if n]
        if candidate in names:
            return candidate
        folded = candidate.casefold()
        for name in names:
            if name.casefold() == folded:
                return name
        # If a parser produced only the suffix of a compact identifier, recover
        # the latest/known compact task name that ends with that suffix.
        if candidate:
            matches = [name for name in names if name.casefold().endswith(folded)]
            if len(matches) == 1:
                return matches[0]
        return candidate or self._latest_task_name()

    def _latest_run_for_task(self, task_name: str) -> dict[str, Any] | None:
        resolved = self._resolve_task_name(task_name) or task_name
        runs = [r for r in self.store.list_json("generated/results") if str(r.get("task_name") or "") == resolved]
        if not runs:
            return None
        runs.sort(key=lambda item: str(item.get("completed_at") or item.get("started_at") or ""), reverse=True)
        return runs[0]


    def delete_participant(self, participant_id: str) -> dict[str, Any]:
        participant_id = str(participant_id or "").strip()
        if not participant_id:
            return {"ok": False, "status": "failed", "error": {"code": "missing_participant_id", "message": "An agent id is required."}}
        result = self.store.delete_json(f"generated/agents/{participant_id}.json")
        if result.get("ok"):
            self._update_community()
            return {"ok": True, "status": "deleted", "participant_id": participant_id}
        return {"ok": False, "status": result.get("status") or "failed", "participant_id": participant_id, "error": result.get("error")}

    def create_runtime_service(self, instruction: str, name: str | None = None) -> dict[str, Any]:
        service_type = self._extract_runtime_service_type(instruction)
        service_id = self._extract_runtime_service_id(instruction, name=name, service_type=service_type)
        configuration = self._extract_runtime_service_configuration(instruction)
        auto_start = self._extract_runtime_service_auto_start(instruction)
        result = runtime_service_manager.create_service(
            service_id=service_id,
            name=name or service_id,
            service_type=service_type,
            configuration=configuration,
            enabled=auto_start,
        )
        service = result.get("service") if isinstance(result, dict) else {}
        status = str(result.get("status") or "created") if isinstance(result, dict) else "failed"
        return {
            "action": "create_runtime_service",
            "origin": "auxiliary_brain",
            "status": status if result.get("ok", True) else "failed",
            "service_id": service_id,
            "service_type": service_type,
            "service": service,
            "final_answer": self._format_runtime_service_result("Runtime service created", result),
        }

    def start_runtime_service(self, service_id: str | None) -> dict[str, Any]:
        sid = self._normalize_runtime_service_name(service_id or "durable_task_dispatcher")
        existing = runtime_service_manager.get_service(sid)
        if not existing and sid == "durable_task_dispatcher":
            runtime_service_manager.create_service(
                service_id=sid,
                name="Durable Task Dispatcher",
                service_type="durable_task_dispatcher",
                configuration={"tick_seconds": 5},
                enabled=False,
            )
        result = runtime_service_manager.start_service(sid)
        return {
            "action": "start_runtime_service",
            "origin": "auxiliary_brain",
            "status": str(result.get("status") or ("completed" if result.get("ok") else "failed")),
            "service_id": sid,
            "service": result.get("service"),
            "final_answer": self._format_runtime_service_result("Runtime service start requested", result),
        }

    def stop_runtime_service(self, service_id: str | None) -> dict[str, Any]:
        sid = self._normalize_runtime_service_name(service_id or "durable_task_dispatcher")
        result = runtime_service_manager.stop_service(sid)
        return {
            "action": "stop_runtime_service",
            "origin": "auxiliary_brain",
            "status": str(result.get("status") or ("completed" if result.get("ok") else "failed")),
            "service_id": sid,
            "service": result.get("service"),
            "final_answer": self._format_runtime_service_result("Runtime service stop requested", result),
        }

    def list_runtime_services(self) -> dict[str, Any]:
        services = runtime_service_manager.list_services()
        lines = ["Runtime services:"]
        if not services:
            lines.append("- No runtime services have been created.")
        for item in services:
            lines.append(f"- {item.get('service_id')}: {item.get('status')} / {item.get('service_type')} / enabled={bool(item.get('enabled'))}")
        return {
            "action": "list_runtime_services",
            "origin": "auxiliary_brain",
            "status": "completed",
            "services": services,
            "final_answer": "\n".join(lines),
        }

    def _extract_runtime_service_type(self, instruction: str) -> str:
        text = str(instruction or "").casefold()
        # Service type is selected from runtime infrastructure semantics, not
        # from a business capability implementation. The durable dispatcher is
        # the generic background worker that runs due persisted task policies.
        if any(token in text for token in ("dispatcher", "scheduled", "schedule", "timer", "timers", "recurring")):
            return "durable_task_dispatcher"
        return "runtime_service"

    def _extract_runtime_service_id(self, instruction: str, *, name: str | None, service_type: str) -> str:
        explicit = self._extract_runtime_service_name(instruction)
        return self._normalize_runtime_service_name(explicit or name or service_type)

    def _extract_runtime_service_name(self, instruction: str) -> str | None:
        text = str(instruction or "")
        patterns = [
            r"runtime service\s+(?:named\s+)?[\"']([^\"']+)[\"']",
            r"service\s+(?:named\s+)?[\"']([^\"']+)[\"']",
            r"runtime service\s+(?:named\s+)?([A-Za-z0-9_\- ]+?)(?:\.|,|$)",
            r"service\s+(?:named\s+)?([A-Za-z0-9_\- ]+?)(?:\.|,|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                value = match.group(1).strip()
                if value:
                    return value
        return None

    def _extract_runtime_service_configuration(self, instruction: str) -> dict[str, Any]:
        cfg: dict[str, Any] = {}
        interval = self._extract_generic_interval_seconds(instruction)
        if interval:
            cfg["tick_seconds"] = max(1, min(interval, 60))
        if "tick" in str(instruction or "").casefold():
            match = re.search(r"tick(?:_seconds)?\s*[:=]\s*(\d+)", str(instruction or ""), flags=re.IGNORECASE)
            if match:
                cfg["tick_seconds"] = max(1, int(match.group(1)))
        cfg.setdefault("tick_seconds", 5)
        return cfg

    def _extract_runtime_service_auto_start(self, instruction: str) -> bool:
        text = str(instruction or "").casefold()
        return any(token in text for token in ("start", "enable", "running", "run mode: background", "background"))

    def _normalize_runtime_service_name(self, value: str | None) -> str:
        text = str(value or "runtime_service").strip().lower()
        aliases = {
            "durable task dispatcher": "durable_task_dispatcher",
            "scheduler runtime service": "durable_task_dispatcher",
            "scheduler service": "durable_task_dispatcher",
            "scheduled task runner": "durable_task_dispatcher",
        }
        if text in aliases:
            return aliases[text]
        text = text.replace(" ", "_")
        allowed = "abcdefghijklmnopqrstuvwxyz0123456789_-"
        safe = "".join(ch for ch in text if ch in allowed).strip("_-")
        return safe or "runtime_service"

    def _format_runtime_service_result(self, title: str, result: dict[str, Any]) -> str:
        service = result.get("service") if isinstance(result, dict) else {}
        if not isinstance(service, dict):
            service = {}
        status = result.get("status") if isinstance(result, dict) else "unknown"
        ok = result.get("ok") if isinstance(result, dict) else False
        lines = [title, f"status: {status}", f"ok: {bool(ok)}"]
        if service:
            lines.append(f"service_id: {service.get('service_id')}")
            lines.append(f"service_type: {service.get('service_type')}")
            lines.append(f"enabled: {bool(service.get('enabled'))}")
        return "\n".join(lines)

    def delete_task_graph(self, task_name: str) -> dict[str, Any]:
        task_name = str(task_name or "").strip()
        if not task_name:
            return {"ok": False, "status": "failed", "error": {"code": "missing_task_name", "message": "A task name is required."}}
        resolved = self._resolve_task_name(task_name) or task_name
        result = self.store.delete_json(f"generated/tasks/{resolved}.json")
        if result.get("ok"):
            self._update_community()
            return {"ok": True, "status": "deleted", "task_name": resolved}
        return {"ok": False, "status": result.get("status") or "failed", "task_name": resolved, "error": result.get("error")}

    def set_task_schedule_enabled(self, task_name: str, enabled: bool) -> dict[str, Any]:
        """Pause or resume a durable schedule policy on a task graph.

        This is intentionally structural: it only toggles schedule_policy.enabled
        and records operational timestamps.  It does not know which agents or
        capabilities the task uses.
        """
        resolved = self._resolve_task_name(task_name) or str(task_name or "").strip()
        if not resolved:
            return {"ok": False, "status": "failed", "error": {"code": "missing_task_name", "message": "A task name is required."}}
        graph = self.store.read_json(f"generated/tasks/{resolved}.json")
        if not graph:
            return {"ok": False, "status": "not_found", "task_name": resolved}
        policy = graph.get("schedule_policy") if isinstance(graph.get("schedule_policy"), dict) else {}
        if not policy or str(policy.get("mode") or "") in {"", "none"}:
            return {"ok": False, "status": "not_scheduled", "task_name": resolved, "message": "The selected task does not declare a durable schedule policy."}
        policy["enabled"] = bool(enabled)
        now = self._now()
        if enabled:
            policy["resumed_at"] = now
            policy["state"] = "active"
            # Resume should be observable soon without waiting for a stale past
            # or missing next_run_at value to be interpreted inconsistently.
            if not policy.get("next_run_at"):
                policy["next_run_at"] = now
        else:
            policy["paused_at"] = now
            policy["state"] = "paused"
        graph["schedule_policy"] = policy
        graph["updated_at"] = now
        self.store.write_json(f"generated/tasks/{resolved}.json", graph)
        self._emit_schedule_observation("schedule_resumed" if enabled else "schedule_paused", task_name=resolved, data={"enabled": bool(enabled), "state": policy.get("state")})
        return {"ok": True, "status": "resumed" if enabled else "paused", "task_name": resolved, "schedule_policy": policy}

    def task_execution_history(self, task_name: str, *, limit: int = 80) -> list[dict[str, Any]]:
        """Return recent scheduler/runtime observations for one task graph."""
        resolved = self._resolve_task_name(task_name) or str(task_name or "").strip()
        if not resolved:
            return []
        events: list[dict[str, Any]] = []
        paths = [
            Path("runtime") / "traces" / "scheduled_tasks" / "scheduler.jsonl",
            Path("runtime") / "traces" / "service_lifecycle" / "scheduled_task_runner.jsonl",
        ]
        seen: set[str] = set()
        for path in paths:
            if not path.exists():
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception:
                continue
            for line in lines[-max(200, int(limit) * 8):]:
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                if not isinstance(item, dict):
                    continue
                if str(item.get("task_name") or "") != resolved:
                    continue
                key = json.dumps(item, sort_keys=True, ensure_ascii=False)
                if key in seen:
                    continue
                seen.add(key)
                events.append(item)
        events.sort(key=lambda item: str(item.get("timestamp") or item.get("time") or ""))
        return events[-max(1, int(limit)):]

    def delete_runtime_capability(self, tool_id: str, *, delete_artifacts: bool = False, delete_profiles: bool = False) -> dict[str, Any]:
        return self.registered_tool_service.delete_tool(tool_id, delete_artifacts=delete_artifacts, delete_profiles=delete_profiles)

    def _structural_source_runtime_context(self, *, task_graph: dict[str, Any], instruction: str | None = None) -> dict[str, Any]:
        texts: list[str] = []
        for value in (instruction, task_graph.get("instruction"), task_graph.get("task_name")):
            if isinstance(value, str) and value.strip():
                texts.append(value.strip())
        tasks = task_graph.get("tasks") if isinstance(task_graph.get("tasks"), list) else []
        for task in tasks:
            if not isinstance(task, dict):
                continue
            for key in ("source_instruction_fragment", "instruction", "description"):
                value = task.get(key)
                if isinstance(value, str) and value.strip():
                    texts.append(value.strip())
        deduped: list[str] = []
        seen: set[str] = set()
        for text in texts:
            key = text.casefold()
            if key not in seen:
                seen.add(key)
                deduped.append(text)
        if not deduped:
            return {}
        material = "\n".join(deduped)
        context: dict[str, Any] = {
            "_source_texts": deduped,
            "_source_text": material,
            # Durable generic source material for later repair/resume.  This is
            # not a business parameter; it lets structural binding recover exact
            # user-provided spans after a delegated run has paused.
            "_original_user_material": material,
        }
        try:
            from ai_core.input_parsing.structured_entity_extractor import StructuredEntityExtractor
            parsed = StructuredEntityExtractor().extract(material, source="original_user_material")
            values = parsed.get("values_by_type") if isinstance(parsed, dict) else {}
            if isinstance(values, dict) and values:
                context["_detected_structural_values"] = values
        except Exception:
            pass
        return context

    def snapshot(self) -> dict[str, Any]:
        conversation_runs = self.store.list_json("traces/conversation_core")
        agent_traces = self.store.list_json("traces/agent_delegation")
        runtime_tool_runs = self.registered_tool_service.list_tool_runs()
        runtime_execution_traces = self.registered_tool_service.list_execution_traces()
        return {
            "origin": "auxiliary_brain",
            "community_id": self.community_id,
            "participants": self.store.list_json("generated/agents"),
            "task_graphs": self.store.list_json("generated/tasks"),
            "task_runs": self.store.list_json("generated/results"),
            "conversation_runs": conversation_runs,
            "runtime_tools": self.registered_tool_service.list_tools(),
            "runtime_tool_runs": runtime_tool_runs,
            "runtime_execution_traces": runtime_execution_traces,
            "deliveries": self.store.list_json("deliveries"),
            "failure_reports": self.verification_foundation.list_reports(limit=80),
            "traces": agent_traces + conversation_runs + runtime_execution_traces,
        }

    async def create_participant(self, instruction: str, name: str | None = None, uploaded_artifacts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        participant_id = new_id("participant")
        participant_name = name or participant_id
        execution_objective = self._derive_execution_objective(instruction, participant_name)
        parameter_contract = await self.parameter_contract_service.build_contract_runtime(
            definition_instruction=instruction,
            execution_objective=execution_objective,
            participant_name=participant_name,
        )
        artifact_refs = self._resolve_uploaded_artifacts_for_instruction(instruction, uploaded_artifacts)
        explicit_runtime_parameters = self._extract_runtime_parameters_from_instruction(instruction)
        # Agent profiles own capability and parameter schema, but never durable
        # task-run values.  Keep the LLM/config-derived schema and clear values
        # so each task execution must collect fresh runtime parameters unless
        # the task instruction explicitly supplies them.
        schema_contract = self._parameter_contract_schema_only(parameter_contract)
        capability_binding = self.registered_tool_agent_binder.bind(
            instruction=instruction,
            participant_name=participant_name,
        )
        if capability_binding:
            schema_contract = capability_binding.get("parameter_contract") or schema_contract
        payload = {
            "participant_id": participant_id,
            "name": participant_name,
            "agent_name": participant_name,
            "display_name": participant_name,
            "role_name": participant_name,
            "instruction": execution_objective,
            "execution_objective": execution_objective,
            "definition_instruction": instruction,
            "parameter_contract": schema_contract,
            "runtime_parameters": {},
            "missing_information": schema_contract.get("missing_information", []),
            "origin": "auxiliary_brain",
            "status": "created",
            "created_at": self._now(),
            "execution_policy": "runtime_registered_tool" if capability_binding else "delegate_to_ai_core",
            "capability_profile": {
                "capability_type": "runtime_registered_tool",
                "tool_id": capability_binding.get("tool_id"),
                "capability": capability_binding.get("capability"),
                "capabilities": capability_binding.get("capabilities") or [],
                "binding_status": capability_binding.get("binding_status"),
                "match_score": capability_binding.get("match_score"),
                "tool_summary": capability_binding.get("tool_summary") or {},
                "execution_policy": capability_binding.get("execution_policy") or {},
            } if capability_binding else {},
            "uploaded_artifacts": artifact_refs,
            "artifact_policy": {
                "bind_uploaded_artifacts_to_agent": bool(artifact_refs),
                "allowed_action": "use_uploaded_file" if artifact_refs else "",
                "parameter_collection_owner": "ui" if artifact_refs else "agent_runtime",
            },
        }
        path = self.store.write_json(f"generated/agents/{participant_id}.json", payload)
        self._update_community()
        return {
            "action": "create_participant",
            "origin": "auxiliary_brain",
            "status": "completed",
            "participant_id": participant_id,
            "agent_name": participant_name,
            "display_name": participant_name,
            "path": str(path),
            "uploaded_artifacts": artifact_refs,
            "capability_profile": payload.get("capability_profile") or {},
            "bound_tool_id": (payload.get("capability_profile") or {}).get("tool_id"),
        }


    def _hydrate_task_step_bindings_from_participants(self, tasks: list[dict[str, Any]], participants: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Copy durable participant binding metadata into task steps.

        The task graph remains a structural workflow record, but viewer and
        execution recovery need the referenced agent's durable capability
        binding to be visible at the step level.  This is a generic merge by
        participant identity; it never checks task names, agent names, or tool
        names.
        """
        by_id = {
            str(p.get("participant_id") or p.get("id") or "").strip(): p
            for p in (participants or [])
            if isinstance(p, dict) and str(p.get("participant_id") or p.get("id") or "").strip()
        }
        hydrated: list[dict[str, Any]] = []
        for task in tasks or []:
            if not isinstance(task, dict):
                continue
            item = dict(task)
            pid = str(item.get("participant_id") or item.get("participant") or item.get("agent_id") or "").strip()
            participant = by_id.get(pid) or {}
            profile = participant.get("capability_profile") if isinstance(participant.get("capability_profile"), dict) else {}
            current_profile = item.get("capability_profile") if isinstance(item.get("capability_profile"), dict) else {}
            if profile and (not current_profile or not str(current_profile.get("capability_type") or current_profile.get("tool_id") or "").strip()):
                item["capability_profile"] = copy.deepcopy(profile)
            contract = participant.get("parameter_contract") if isinstance(participant.get("parameter_contract"), dict) else {}
            current_contract = item.get("parameter_contract") if isinstance(item.get("parameter_contract"), dict) else {}
            params = contract.get("parameters") if isinstance(contract.get("parameters"), list) else []
            current_params = current_contract.get("parameters") if isinstance(current_contract.get("parameters"), list) else []
            if params and not current_params:
                item["parameter_contract"] = copy.deepcopy(contract)
            policy = str(participant.get("execution_policy") or "").strip()
            if policy and not str(item.get("execution_policy") or "").strip():
                item["execution_policy"] = policy
            hydrated.append(item)
        return hydrated

    def _safe_task_asset_name(self, task_name: str) -> str:
        value = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(task_name or "").strip()).strip("._")
        return value or "task"

    def _instruction_fingerprint(self, instruction: str) -> str:
        return hashlib.sha256(str(instruction or "").encode("utf-8")).hexdigest()

    def _next_task_revision_metadata(self, task_name: str, instruction: str) -> dict[str, Any]:
        """Create a generic lifecycle identity for a task graph revision.

        A task is a durable composition snapshot.  Each create/edit operation
        must mint its own graph/plan revision so execution never depends on a
        mutable natural-language note whose graph was produced by an earlier
        version.  This is runtime lifecycle metadata only; it does not inspect
        any business words, agents, or capabilities.
        """
        existing = self.store.read_json(f"generated/tasks/{task_name}.json")
        previous_revision = existing.get("active_revision_id") or existing.get("revision_id") if isinstance(existing, dict) else None
        previous_task_revision = existing.get("task_revision") if isinstance(existing, dict) else None
        try:
            next_revision = int(previous_task_revision or 0) + 1
        except Exception:
            next_revision = 1
        revision_id = new_id("task_revision")
        graph_revision_id = new_id("graph_revision")
        plan_revision_id = new_id("plan_revision")
        now = self._now()
        return {
            "task_revision": next_revision,
            "graph_revision": next_revision,
            "plan_revision": next_revision,
            "revision_id": revision_id,
            "active_revision_id": revision_id,
            "graph_revision_id": graph_revision_id,
            "plan_revision_id": plan_revision_id,
            "previous_revision_id": previous_revision,
            "source_instruction_fingerprint": self._instruction_fingerprint(instruction),
            "revision_created_at": now,
            "updated_at": now,
            "lifecycle": {
                "state": "active",
                "asset_model": "task_owns_independent_graph_and_plan_revision",
                "task_revision": next_revision,
                "graph_revision": next_revision,
                "plan_revision": next_revision,
                "active_revision_id": revision_id,
                "previous_revision_id": previous_revision,
            },
        }

    def _write_task_revision_asset(self, payload: dict[str, Any]) -> None:
        task_name = str(payload.get("task_name") or payload.get("graph_id") or "task").strip() or "task"
        revision_id = str(payload.get("active_revision_id") or payload.get("revision_id") or new_id("task_revision"))
        safe_name = self._safe_task_asset_name(task_name)
        try:
            self.store.write_json(f"generated/task_revisions/{safe_name}/{revision_id}.json", copy.deepcopy(payload))
        except Exception:
            return

    def _task_instruction_changed(self, task_graph: dict[str, Any]) -> bool:
        if not isinstance(task_graph, dict):
            return False
        instruction = str(task_graph.get("instruction") or "")
        if not instruction.strip():
            return False
        expected = str(task_graph.get("source_instruction_fingerprint") or "").strip()
        if not expected:
            return False
        return expected != self._instruction_fingerprint(instruction)

    def _rebuild_task_graph_from_current_instruction(self, task_graph: dict[str, Any]) -> dict[str, Any]:
        """Rebuild a task's own graph/plan when its source instruction changed.

        This is a generic invalidation hook.  It lets an edited task definition
        produce a fresh graph/plan revision while preserving agent and
        capability definitions.  Run history remains in generated/results.
        """
        if not isinstance(task_graph, dict):
            return task_graph
        task_name = str(task_graph.get("task_name") or task_graph.get("graph_id") or "").strip()
        instruction = str(task_graph.get("instruction") or "")
        if not task_name or not instruction.strip():
            return task_graph
        uploaded_artifacts = task_graph.get("uploaded_artifacts") if isinstance(task_graph.get("uploaded_artifacts"), list) else None
        rebuilt = self.create_task_graph(instruction, task_name, uploaded_artifacts=uploaded_artifacts)
        if rebuilt.get("status") != "completed":
            return task_graph
        latest = self.store.read_json(f"generated/tasks/{task_name}.json")
        return latest or task_graph

    def rebuild_task_graph(self, task_name: str) -> dict[str, Any]:
        resolved = self._resolve_task_name(task_name) or str(task_name or "").strip()
        if not resolved:
            return {"ok": False, "status": "failed", "error": {"code": "missing_task_name", "message": "A task name is required."}}
        current = self.store.read_json(f"generated/tasks/{resolved}.json")
        if not current:
            return {"ok": False, "status": "not_found", "task_name": resolved}
        instruction = str(current.get("instruction") or "")
        if not instruction.strip():
            return {"ok": False, "status": "failed", "task_name": resolved, "error": {"code": "missing_instruction", "message": "The task has no source instruction to rebuild."}}
        rebuilt = self.create_task_graph(instruction, resolved, uploaded_artifacts=current.get("uploaded_artifacts") if isinstance(current.get("uploaded_artifacts"), list) else None)
        return {"ok": rebuilt.get("status") == "completed", "status": rebuilt.get("status"), "task_name": resolved, "rebuild": rebuilt}

    def update_task_graph_instruction(self, task_name: str, instruction: str, uploaded_artifacts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Edit a task by creating a new active graph/plan revision."""
        resolved = self._resolve_task_name(task_name) or str(task_name or "").strip()
        if not resolved:
            return {"ok": False, "status": "failed", "error": {"code": "missing_task_name", "message": "A task name is required."}}
        if not str(instruction or "").strip():
            return {"ok": False, "status": "failed", "task_name": resolved, "error": {"code": "missing_instruction", "message": "A task instruction is required."}}
        current = self.store.read_json(f"generated/tasks/{resolved}.json")
        if not current:
            return {"ok": False, "status": "not_found", "task_name": resolved}
        artifacts = uploaded_artifacts if uploaded_artifacts is not None else current.get("uploaded_artifacts") if isinstance(current.get("uploaded_artifacts"), list) else None
        rebuilt = self.create_task_graph(str(instruction), resolved, uploaded_artifacts=artifacts)
        return {"ok": rebuilt.get("status") == "completed", "status": rebuilt.get("status"), "task_name": resolved, "revision": rebuilt}


    def _canonicalize_task_participant_catalog(self, participants: list[dict[str, Any]], *, instruction: str = "") -> list[dict[str, Any]]:
        """Return a clean durable participant catalog for task graph planning.

        Task-local generated intermediate participants are persisted for old run
        compatibility, but they must not be offered as reusable agents for a new
        task.  Also, multiple durable files may point to the same logical agent
        after repeated development/re-acquisition.  The task graph should bind a
        logical agent once, then capability metadata should hang under that
        participant rather than creating duplicate participant nodes.
        """
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in participants or []:
            if not isinstance(item, dict):
                continue
            if self._is_task_local_generated_participant(item):
                continue
            key = self._logical_participant_key(item)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out

    def _is_task_local_generated_participant(self, participant: dict[str, Any]) -> bool:
        generated_by = str(participant.get("generated_by") or "").strip()
        workflow_step_type = str(participant.get("workflow_step_type") or "").strip()
        if workflow_step_type == "semantic_intermediate_step":
            return True
        if generated_by in {"semantic_workflow_planning", "structural_workflow_planning"}:
            return True
        return False

    def _logical_participant_key(self, participant: dict[str, Any]) -> str:
        name = str(
            participant.get("display_name")
            or participant.get("agent_name")
            or participant.get("name")
            or participant.get("participant_id")
            or participant.get("id")
            or ""
        ).strip().casefold()
        profile = participant.get("capability_profile") if isinstance(participant.get("capability_profile"), dict) else {}
        tool_id = str(profile.get("tool_id") or profile.get("capability") or "").strip().casefold()
        cap_type = str(profile.get("capability_type") or "").strip().casefold()
        execution_policy = participant.get("execution_policy") if isinstance(participant.get("execution_policy"), dict) else {}
        method = str(execution_policy.get("execution_method") or participant.get("execution_policy") or "").strip().casefold()
        return "|".join([name, cap_type, tool_id, method])

    def create_task_graph(self, instruction: str, name: str | None = None, uploaded_artifacts: list[dict[str, Any]] | None = None, presentation_profile: str | None = None) -> dict[str, Any]:
        graph_id = new_id("graph")
        task_name = name or graph_id
        participants = self._canonicalize_task_participant_catalog(
            self.store.list_json("generated/agents"),
            instruction=instruction,
        )
        artifact_refs = self._resolve_uploaded_artifacts_for_instruction(instruction, uploaded_artifacts)
        explicit_runtime_parameters = self._extract_runtime_parameters_from_instruction(instruction)
        schedule_policy = self._extract_schedule_policy_from_instruction(instruction)
        mentioned_participants = self._participants_mentioned_in_message(instruction, participants)
        if len(mentioned_participants) == 1:
            semantic_plan = {"steps": [], "coverage_notes": ["semantic_planner_skipped_explicit_single_participant"]}
        else:
            semantic_plan = self.runtime_semantic_planner.build_plan(
                instruction=instruction,
                participants=participants,
                run_id=graph_id,
            )
        workflow_plan = self.instruction_workflow_planner.plan(
            instruction=instruction,
            participants=participants,
            graph_id=graph_id,
            new_id_fn=new_id,
            semantic_plan=semantic_plan,
        )
        explicit_runtime_parameters.update(
            self._extract_step_scoped_runtime_parameters_from_tasks(workflow_plan.tasks)
        )
        # Do not persist planner-generated local participants before static
        # validation. If validation fails, persisting them pollutes the durable
        # agent catalog and the UI starts showing false agents such as
        # "Call X Agent. Parameters...". Generated participants are only
        # runtime graph assets after the task graph is accepted.
        selected_ids = [p.get("participant_id") for p in workflow_plan.selected_participants]
        workflow_tasks = self._hydrate_task_step_bindings_from_participants(
            workflow_plan.tasks,
            workflow_plan.selected_participants,
        )
        explicit_runtime_parameters.update(
            self._extract_named_parameter_blocks_from_instruction(instruction, workflow_plan.selected_participants)
        )
        if schedule_policy.get("enabled"):
            controller_ids = self._derive_execution_controller_participant_ids(
                tasks=workflow_tasks,
                participants=workflow_plan.selected_participants,
                runtime_parameters=explicit_runtime_parameters,
            )
            if controller_ids:
                schedule_policy = dict(schedule_policy)
                schedule_policy["controller_participant_ids"] = controller_ids

        static_validation = self._validate_task_graph_static(
            instruction=instruction,
            participants=participants,
            selected_participants=workflow_plan.selected_participants,
            generated_participants=workflow_plan.generated_participants,
            tasks=workflow_tasks,
        )
        if not static_validation.get("passed"):
            failure_payload = {
                "graph_id": graph_id,
                "task_name": task_name,
                "community_id": self.community_id,
                "instruction": instruction,
                "origin": "auxiliary_brain",
                "status": "static_validation_failed",
                "created_at": self._now(),
                "execution_policy": "blocked_before_task_graph_persistence",
                "selected_participant_ids": selected_ids,
                "uploaded_artifacts": artifact_refs,
                "runtime_parameters": explicit_runtime_parameters,
                "schedule_policy": schedule_policy,
                "tasks": workflow_tasks,
                "static_validation": static_validation,
                "instruction_coverage": workflow_plan.coverage,
                "presentation_profile": PresentationProfileRegistry.normalize(presentation_profile),
            }
            failure_report = self._build_static_validation_failure_report(failure_payload, presentation_profile=presentation_profile)
            self._write_static_validation_failure_report(failure_payload, report=failure_report)
            self._update_community()
            user_message = (failure_report.get("payload") or {}).get("user_message")
            final_answer = self._format_failure_user_message(user_message) if isinstance(user_message, dict) else "Task graph creation failed."
            return {
                "action": "create_task_graph",
                "origin": "auxiliary_brain",
                "status": "failed",
                "failure_class": "task_graph_static_validation_failed",
                "graph_id": graph_id,
                "task_name": task_name,
                "message": final_answer,
                "final_answer": final_answer,
                "user_message": user_message,
                "failure_report": failure_report,
                "static_validation": static_validation,
            }
        # Task graphs do not own durable parameter values.  Parameter schemas live
        # on participants, while uploaded artifact parameters are discovered from
        # the selected artifact during execution_preparation.  Keeping a blank
        # task-level contract here prevents stale values from leaking into
        # unrelated future runs and avoids referencing an undefined
        # participant-only parameter_contract.
        for generated_participant in workflow_plan.generated_participants:
            generated_participant.setdefault("created_at", self._now())
            pid = str(generated_participant.get("participant_id") or "").strip()
            if pid:
                self.store.write_json(f"generated/agents/{pid}.json", generated_participant)

        schema_contract = {
            "contract_type": "task_runtime_parameter_contract",
            "parameters": [],
            "missing_information": [],
            "runtime_scope": "task_run",
        }
        payload = {
            "graph_id": graph_id,
            "task_name": task_name,
            "community_id": self.community_id,
            "instruction": instruction,
            "origin": "auxiliary_brain",
            "status": "created",
            "created_at": self._now(),
            "execution_policy": "delegated_participant_execution_via_ai_core",
            "selected_participant_ids": selected_ids,
            "uploaded_artifacts": artifact_refs,
            "parameter_contract": schema_contract,
            "runtime_parameters": explicit_runtime_parameters,
            "schedule_policy": schedule_policy,
            "tasks": workflow_tasks,
            "instruction_coverage": workflow_plan.coverage,
            "workflow_planning": {
                "mode": workflow_plan.coverage.get("planning_mode"),
                "semantic_step_count": workflow_plan.coverage.get("semantic_step_count"),
                "semantic_plan_status": (semantic_plan.get("coverage_notes") or []),
                "generated_participant_ids": [p.get("participant_id") for p in workflow_plan.generated_participants],
                "step_count": len(workflow_tasks),
                "coverage_status": workflow_plan.coverage.get("status"),
            },
            "final_synthesis_owner": "ai_core",
        }
        payload.update(self._next_task_revision_metadata(task_name, instruction))
        self._write_task_revision_asset(payload)
        path = self.store.write_json(f"generated/tasks/{task_name}.json", payload)
        if isinstance(schedule_policy, dict) and schedule_policy.get("enabled"):
            self._emit_schedule_observation(
                "schedule_saved",
                task_name=task_name,
                data={
                    "interval_seconds": schedule_policy.get("interval_seconds"),
                    "next_run_at": schedule_policy.get("next_run_at"),
                    "controller_participant_ids": schedule_policy.get("controller_participant_ids") or [],
                },
            )
        self._update_community()
        service_suggestion = runtime_service_manager.suggest_service_for_context(payload)
        final_answer = "Task graph created."
        if service_suggestion:
            final_answer += "\nRuntime service suggestion: create and start a durable task dispatcher so recurring policies can run in the background."
        return {
            "action": "create_task_graph",
            "origin": "auxiliary_brain",
            "status": "completed",
            "graph_id": graph_id,
            "task_name": task_name,
            "path": str(path),
            "uploaded_artifacts": artifact_refs,
            "runtime_service_suggestion": service_suggestion,
            "final_answer": final_answer,
        }


    def _validate_task_graph_static(
        self,
        *,
        instruction: str,
        participants: list[dict[str, Any]] | None,
        selected_participants: list[dict[str, Any]] | None,
        generated_participants: list[dict[str, Any]] | None,
        tasks: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        """Validate graph structure before persisting a task graph.

        The validator is intentionally generic.  It checks structural facts that
        are knowable at task creation time: declared participant references must
        resolve to durable participants, and explicit step-template references
        must target declared steps.  It does not know domains or capability
        business semantics.
        """
        text = str(instruction or "")
        participants = participants if isinstance(participants, list) else []
        selected_participants = selected_participants if isinstance(selected_participants, list) else []
        generated_participants = generated_participants if isinstance(generated_participants, list) else []
        tasks = tasks if isinstance(tasks, list) else []
        issues: list[dict[str, Any]] = []

        known_names = self._static_participant_name_index(participants)
        selected_names = self._static_participant_name_index(selected_participants)
        declared_refs = self._extract_declared_participant_references(text)
        for ref in declared_refs:
            ref_name = str(ref.get("name") or "").strip()
            norm = self._static_normalize_name(ref_name)
            if not norm:
                continue
            if norm not in known_names:
                suggestions = self._static_suggest_participants(norm, known_names)
                issues.append({
                    "level": "create_task_graph",
                    "check": "declared_participant_reference_resolves",
                    "passed": False,
                    "failure_class": "agent_reference_not_found" if not suggestions else "agent_reference_ambiguous",
                    "message": "A declared participant reference did not resolve to an existing durable participant.",
                    "reference": ref_name,
                    "line": ref.get("line"),
                    "suggestions": suggestions,
                    "suggested_location": ["auxiliary_brain.studio.task_graph_static_validation", "agent_reference_resolution"],
                })

        for generated in generated_participants:
            if not isinstance(generated, dict):
                continue
            if not self._is_task_local_generated_participant(generated):
                continue
            source = "\n".join(str(generated.get(k) or "") for k in ("display_name", "agent_name", "name", "definition_instruction", "instruction", "execution_objective", "source_instruction_fragment"))
            generated_refs = self._extract_declared_participant_references(source)
            for ref in generated_refs:
                ref_name = str(ref.get("name") or "").strip()
                norm = self._static_normalize_name(ref_name)
                if norm and norm not in known_names and norm not in selected_names:
                    issues.append({
                        "level": "create_task_graph",
                        "check": "generated_step_must_not_mask_unresolved_participant_reference",
                        "passed": False,
                        "failure_class": "agent_reference_not_found",
                        "message": "A generated local step appears to be an unresolved participant reference. Task graph creation is blocked to avoid creating a false agent node.",
                        "reference": ref_name,
                        "generated_participant_id": generated.get("participant_id"),
                        "suggestions": self._static_suggest_participants(norm, known_names),
                        "suggested_location": ["auxiliary_brain.studio.instruction_workflow_planner", "participant_catalog_resolution"],
                    })

        declared_steps = self._extract_declared_step_ids(text)
        task_step_aliases = {str(t.get("source_step_id") or "").strip().casefold() for t in tasks if isinstance(t, dict) and str(t.get("source_step_id") or "").strip()}
        for template in self._extract_template_references(text):
            root = str(template.get("root") or "").strip()
            if not root:
                continue
            root_norm = root.casefold()
            step_match = re.fullmatch(r"step\s*_?\s*(\d+)", root_norm, flags=re.I)
            if step_match:
                canonical = f"step{step_match.group(1)}".casefold()
                if canonical not in declared_steps and root_norm not in task_step_aliases:
                    issues.append({
                        "level": "create_task_graph",
                        "check": "template_step_reference_exists",
                        "passed": False,
                        "failure_class": "template_reference_not_found",
                        "message": "A template reference points to a step that is not declared in this task instruction.",
                        "reference": template.get("raw"),
                        "root": root,
                        "declared_steps": sorted(declared_steps),
                        "suggested_location": ["verification_brain.template_verification", "task_graph_static_validation"],
                    })

        return {
            "passed": not issues,
            "stage": "create_task_graph",
            "checks": [
                {"name": "declared_participant_references", "passed": not any(i.get("check") in {"declared_participant_reference_resolves", "generated_step_must_not_mask_unresolved_participant_reference"} for i in issues)},
                {"name": "template_step_references", "passed": not any(i.get("check") == "template_step_reference_exists" for i in issues)},
            ],
            "issues": issues,
        }

    def _extract_declared_participant_references(self, text: str) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        for line_no, line in enumerate(str(text or "").splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            match = re.search(r"(?i)\b(?:call|use|run|execute|invoke)\s+(?P<name>[^\n\r.:;]+?\bagent\b)", stripped)
            if not match:
                continue
            name = re.sub(r"(?i)^\s*(?:the|a|an)\s+", "", str(match.group("name") or "")).strip()
            if name:
                refs.append({"name": name, "line": line_no, "source": stripped})
        return refs

    def _extract_declared_step_ids(self, text: str) -> set[str]:
        ids: set[str] = set()
        for match in re.finditer(r"(?im)^\s*step\s*(\d+)\s*[:.)-]?", str(text or "")):
            ids.add(f"step{match.group(1)}".casefold())
        return ids

    def _extract_template_references(self, text: str) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        for match in re.finditer(r"\{\{\s*([^{}]+?)\s*\}\}", str(text or "")):
            expr = str(match.group(1) or "").strip()
            root = re.split(r"[.\[\s]", expr, maxsplit=1)[0].strip()
            refs.append({"raw": match.group(0), "expression": expr, "root": root})
        return refs

    def _static_participant_name_index(self, participants: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        index: dict[str, dict[str, Any]] = {}
        for participant in participants or []:
            if not isinstance(participant, dict):
                continue
            values = [
                participant.get("display_name"),
                participant.get("agent_name"),
                participant.get("name"),
                participant.get("role_name"),
                participant.get("participant_id"),
                participant.get("id"),
            ]
            for value in values:
                norm = self._static_normalize_name(value)
                if norm and norm not in index:
                    index[norm] = participant
        return index

    def _static_normalize_name(self, value: Any) -> str:
        raw = str(value or "").strip()
        raw = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", raw)
        text = raw.casefold()
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return " ".join(text.split())

    def _static_suggest_participants(self, normalized_ref: str, known_names: dict[str, dict[str, Any]]) -> list[str]:
        structural_terms = {"agent", "participant", "runtime"}
        ref_tokens = {t for t in str(normalized_ref or "").split() if t not in structural_terms}
        scored: list[tuple[int, str]] = []
        for norm, participant in known_names.items():
            tokens = {t for t in norm.split() if t not in structural_terms}
            if not tokens:
                continue
            score = len(ref_tokens & tokens)
            if score:
                name = str(participant.get("display_name") or participant.get("agent_name") or participant.get("name") or participant.get("participant_id") or "").strip()
                if name:
                    scored.append((score, name))
        scored.sort(key=lambda item: (-item[0], item[1].casefold()))
        out: list[str] = []
        for _, name in scored:
            if name not in out:
                out.append(name)
            if len(out) >= 5:
                break
        return out

    def _build_static_validation_failure_report(self, payload: dict[str, Any], *, presentation_profile: str | None = None) -> dict[str, Any]:
        graph_id = self._safe_filename(payload.get("graph_id") or payload.get("task_name") or "static_validation")
        report = {
            "report_id": f"failure_{graph_id}",
            "status": "failure_detected",
            "failure_class": "task_graph_static_validation_failed",
            "stage": "create_task_graph",
            "task_name": payload.get("task_name"),
            "graph_id": payload.get("graph_id"),
            "failed_checks": (payload.get("static_validation") or {}).get("issues") if isinstance(payload.get("static_validation"), dict) else [],
            "suggested_owner": "auxiliary_brain",
            "suggested_location": ["auxiliary_brain.studio.create_task_graph", "task_graph_static_validation"],
            "created_at": self._now(),
            "payload": payload,
        }
        try:
            user_message = self.failure_message_renderer.render(report, allow_llm=True, profile=presentation_profile or payload.get("presentation_profile")).to_dict()
        except Exception as exc:
            user_message = {
                "title": "Task graph creation failed",
                "summary": "The task could not be converted into a safe executable graph.",
                "reasons": [str(exc)[:300]],
                "suggestions": ["Inspect the static validation report."],
                "source": "presentation_brain.fallback",
            }
        report["payload"] = dict(report.get("payload") or {})
        report["payload"]["user_message"] = user_message
        return report

    def _format_failure_user_message(self, user_message: dict[str, Any] | None) -> str:
        """Format Presentation Brain failure message for simple UI surfaces."""
        if not isinstance(user_message, dict):
            return "Task graph creation failed."
        lines: list[str] = []
        title = str(user_message.get("title") or "Task graph creation failed.").strip()
        summary = str(user_message.get("summary") or "").strip()
        if title:
            lines.append(title)
        if summary:
            lines.append("")
            lines.append(summary)
        reasons = user_message.get("reasons") if isinstance(user_message.get("reasons"), list) else []
        if reasons:
            lines.append("")
            lines.append("Reasons:")
            for item in reasons[:6]:
                text = str(item or "").strip()
                if text:
                    lines.append(f"- {text}")
        suggestions = user_message.get("suggestions") if isinstance(user_message.get("suggestions"), list) else []
        if suggestions:
            lines.append("")
            lines.append("Suggested fixes:")
            for item in suggestions[:6]:
                text = str(item or "").strip()
                if text:
                    lines.append(f"- {text}")
        location = user_message.get("location") if isinstance(user_message.get("location"), list) else []
        if location:
            lines.append("")
            lines.append("Where to check:")
            for item in location[:8]:
                text = str(item or "").strip()
                if text:
                    lines.append(f"- {text}")
        technical = user_message.get("technical") if isinstance(user_message.get("technical"), dict) else {}
        if technical:
            lines.append("")
            lines.append("Technical details:")
            for key, value in list(technical.items())[:10]:
                if value not in (None, "", [], {}):
                    lines.append(f"- {key}: {value}")
        return "\n".join(lines).strip() or "Task graph creation failed."

    def _write_static_validation_failure_report(self, payload: dict[str, Any], *, report: dict[str, Any] | None = None) -> None:
        try:
            root = Path("runtime/generated/failure_reports")
            root.mkdir(parents=True, exist_ok=True)
            report = report if isinstance(report, dict) else self._build_static_validation_failure_report(payload)
            (root / f"{report['report_id']}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        except Exception:
            return

    def _safe_filename(self, value: Any) -> str:
        text = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(value or "")).strip("_")
        return text[:120] or "unknown"

    async def _maybe_execute_direct_participant_invocation(
        self,
        message: str,
        *,
        provided_inputs: dict[str, Any] | None = None,
        uploaded_artifacts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """Execute a one-off task when the text names an existing participant.

        This is a generic bridge from natural language into the existing
        Agent/Task execution path.  It does not infer what a capability does;
        it only resolves a durable participant by name and delegates to the
        same task execution pipeline used by saved tasks.
        """
        participant = self._find_participant_mentioned_in_message(message)
        if not participant:
            return None
        task_name = self._create_direct_participant_task_graph(
            message=message,
            participant=participant,
            provided_inputs=provided_inputs,
            uploaded_artifacts=uploaded_artifacts,
        )
        return await self.execute_task(task_name, provided_inputs=provided_inputs, instruction=message)

    def _find_participant_mentioned_in_message(self, message: str) -> dict[str, Any] | None:
        text = str(message or "")
        if not text.strip():
            return None
        participants = self._canonicalize_task_participant_catalog(
            self.store.list_json("generated/agents"),
            instruction=message,
        )
        candidates: list[tuple[int, dict[str, Any]]] = []
        lowered = text.casefold()
        for participant in participants:
            if not isinstance(participant, dict):
                continue
            names = []
            for key in ("display_name", "agent_name", "name", "role_name", "participant_id"):
                value = str(participant.get(key) or "").strip()
                if value and value not in names:
                    names.append(value)
            for name in names:
                if self._contains_named_entity(lowered, name):
                    candidates.append((len(name), participant))
                    break
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def _participants_mentioned_in_message(self, message: str, participants: list[dict[str, Any]]) -> list[dict[str, Any]]:
        text = str(message or "")
        if not text.strip():
            return []
        lowered = text.casefold()
        mentioned: list[tuple[int, str, dict[str, Any]]] = []
        seen: set[str] = set()
        for participant in participants:
            if not isinstance(participant, dict):
                continue
            pid = str(participant.get("participant_id") or participant.get("id") or participant.get("name") or "").strip()
            names = []
            for key in ("display_name", "agent_name", "name", "role_name", "participant_id"):
                value = str(participant.get(key) or "").strip()
                if value and value not in names:
                    names.append(value)
            for name in names:
                if self._contains_named_entity(lowered, name):
                    dedupe_key = pid or self._logical_participant_key(participant)
                    if dedupe_key and dedupe_key not in seen:
                        seen.add(dedupe_key)
                        mentioned.append((len(name), dedupe_key, participant))
                    break
        mentioned.sort(key=lambda item: item[0], reverse=True)
        return [item[2] for item in mentioned]

    def _contains_named_entity(self, lowered_text: str, name: str) -> bool:
        normalized_name = str(name or "").strip()
        if not normalized_name:
            return False
        # Preserve exact multi-word identities while still allowing compact ids.
        pattern = r"(?<![A-Za-z0-9_])" + re.escape(normalized_name.casefold()) + r"(?![A-Za-z0-9_])"
        return re.search(pattern, lowered_text) is not None

    def _create_direct_participant_task_graph(
        self,
        *,
        message: str,
        participant: dict[str, Any],
        provided_inputs: dict[str, Any] | None = None,
        uploaded_artifacts: list[dict[str, Any]] | None = None,
    ) -> str:
        graph_id = new_id("direct_agent_graph")
        task_name = graph_id
        participant_id = str(participant.get("participant_id") or participant.get("id") or "").strip()
        participant_name = str(participant.get("display_name") or participant.get("agent_name") or participant.get("name") or participant_id or "participant")
        runtime_parameters: dict[str, Any] = {}
        runtime_parameters.update(self._extract_runtime_parameters_from_instruction(message))
        runtime_parameters.update(self._extract_participant_schema_parameters_from_instruction(message, participant))
        # Store generic original source material at creation time so one-off
        # delegated executions can resume repair even if the later resume call
        # only receives a boolean confirmation.
        runtime_parameters.update(self._structural_source_runtime_context(task_graph={"instruction": str(message or "")}, instruction=message))
        if isinstance(provided_inputs, dict):
            runtime_parameters.update({
                k: v
                for k, v in provided_inputs.items()
                if v not in (None, "", [], {}) and not str(k).startswith("_scheduled_") and str(k) not in {"_payload_only_selected_participant_ids", "_runtime_state_run_id", "_state_run_id", "_perception_package"}
            })
        artifact_refs = uploaded_artifacts if isinstance(uploaded_artifacts, list) else []
        task_graph = {
            "graph_id": graph_id,
            "task_name": task_name,
            "community_id": self.community_id,
            "instruction": str(message or ""),
            "origin": "auxiliary_brain",
            "status": "created",
            "created_at": self._now(),
            "execution_policy": "delegated_participant_execution_via_ai_core",
            "selected_participant_ids": [participant_id] if participant_id else [],
            "uploaded_artifacts": artifact_refs,
            "parameter_contract": {
                "contract_type": "task_runtime_parameter_contract",
                "parameters": [],
                "missing_information": [],
                "runtime_scope": "task_run",
            },
            "runtime_parameters": runtime_parameters,
            "tasks": [{
                "task_id": f"{graph_id}_delegate_1",
                "participant_id": participant_id,
                "participant_display_name": participant_name,
                "execution_owner": "ai_core",
                "status": "pending",
                "step_type": "participant_execution",
                "depends_on": [],
                "source_step_id": task_name,
                "source_instruction_fragment": str(message or ""),
                "capability_profile": participant.get("capability_profile") if isinstance(participant.get("capability_profile"), dict) else {},
                "input_contract": {
                    "contract_type": "runtime_step_input_contract",
                    "bound_from_upstream": [],
                    "accepts_verified_material": False,
                    "user_input_required_for_bound_material": False,
                },
                "output_contract": {
                    "contract_type": "runtime_step_output_contract",
                    "produces_verified_material": True,
                    "planner_metadata_is_not_result_material": True,
                },
            }],
            "workflow_planning": {
                "mode": "direct_existing_participant_invocation",
                "semantic_step_count": 1,
                "generated_participant_ids": [],
                "step_count": 1,
                "coverage_status": "passed",
            },
            "instruction_coverage": {
                "status": "passed",
                "covered_actions": [{
                    "step_id": task_name,
                    "type": "participant_execution",
                    "participant_id": participant_id,
                }],
                "uncovered_fragments": [],
                "selected_participant_count": 1,
                "generated_step_count": 0,
                "planning_mode": "direct_existing_participant_invocation",
            },
            "final_synthesis_owner": "ai_core",
        }
        self.store.write_json(f"generated/tasks/{task_name}.json", task_graph)
        return task_name

    def _extract_participant_schema_parameters_from_instruction(self, instruction: str, participant: dict[str, Any]) -> dict[str, Any]:
        """Extract values for fields declared by the participant contract.

        This is field-name driven, not capability-specific.  It handles quoted
        values and short unquoted values adjacent to declared parameter names so
        a natural one-off invocation can prefill the same form fields that the
        old Agent/Task parameter flow already exposes.
        """
        text = str(instruction or "")
        contract = participant.get("parameter_contract") if isinstance(participant.get("parameter_contract"), dict) else {}
        params = contract.get("parameters") if isinstance(contract.get("parameters"), list) else []
        names: list[str] = []
        for param in params:
            if not isinstance(param, dict):
                continue
            name = str(param.get("name") or param.get("parameter_name") or "").strip()
            if name and name not in names:
                names.append(name)
        out: dict[str, Any] = {}
        for name in names:
            value = self._extract_named_value_from_instruction(text, name)
            if value not in (None, "", [], {}):
                out[name] = value
                pid = str(participant.get("participant_id") or participant.get("id") or "").strip()
                pname = str(participant.get("display_name") or participant.get("agent_name") or participant.get("name") or "").strip()
                safe_pname = re.sub(r"[^A-Za-z0-9_]+", "_", pname).strip("_")
                if pid:
                    out.setdefault(f"{pid}.{name}", value)
                if pname:
                    out.setdefault(f"{pname}.{name}", value)
                if safe_pname:
                    out.setdefault(f"{safe_pname}.{name}", value)
        return out

    def _extract_named_value_from_instruction(self, text: str, field_name: str) -> Any:
        name = str(field_name or "").strip()
        if not name:
            return None
        token_pattern = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])", flags=re.I)
        candidates: list[str] = []
        for match in token_pattern.finditer(text):
            tail = text[match.end():].lstrip()
            if not tail:
                continue
            if tail[0] in {"'", '"'}:
                quote = tail[0]
                closing = tail.find(quote, 1)
                if closing > 0:
                    value = tail[1:closing].strip()
                    if value:
                        candidates.append(value)
                continue
            # Stop before the next connector + declared-looking assignment, or
            # at ordinary sentence/list delimiters.  This keeps extraction
            # generic while preventing one field from swallowing following
            # fields in a natural command.
            stop_match = re.search(
                r"\s+(?:with|and|using|for)\s+[A-Za-z_][A-Za-z0-9_]*\s+[\"']|"
                r"\s+[A-Za-z_][A-Za-z0-9_]*\s+[\"']|"
                r"[,;\n!?]",
                tail,
                flags=re.I,
            )
            value = tail[: stop_match.start()].strip() if stop_match else tail.strip()
            value = value.strip().strip("'\"")
            if value and len(value.split()) <= 6:
                candidates.append(value)
        if not candidates:
            return None
        return candidates[-1]


    def _attach_verification_report(
        self,
        *,
        task_graph: dict[str, Any],
        participants: list[dict[str, Any]],
        run_payload: dict[str, Any],
        response: dict[str, Any] | None = None,
        stage: str = "post_execution",
    ) -> dict[str, Any] | None:
        """Run v19 verification/evidence foundation and persist report if needed.

        This method is deliberately side-effect limited: it writes a failure
        report and attaches it to the run payload/response. It does not apply a
        patch, change the task graph, or retry execution.
        """
        try:
            report = self.verification_foundation.inspect_run(
                task_graph=task_graph,
                participants=participants,
                run_payload=run_payload,
                stage=stage,
            )
        except Exception as exc:
            report = None
            try:
                path = Path("runtime") / "traces" / "verification" / "verification_events.jsonl"
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({
                        "created_at": self._now(),
                        "event": "verification_foundation_failed",
                        "error_type": exc.__class__.__name__,
                        "error": str(exc),
                        "task_name": run_payload.get("task_name") if isinstance(run_payload, dict) else "",
                        "run_id": run_payload.get("run_id") if isinstance(run_payload, dict) else "",
                    }, ensure_ascii=False) + "\n")
            except Exception:
                pass
        if report is None:
            confirmations = run_payload.get("side_effect_confirmations") if isinstance(run_payload, dict) else None
            if response is not None and isinstance(confirmations, list) and confirmations:
                response["side_effect_confirmation"] = {
                    "status": "pending_user_feedback_default_success",
                    "default_assumption": "success_until_user_reports_failure",
                    "confirmations": confirmations,
                }
                response.setdefault("verification", {})
                if isinstance(response.get("verification"), dict):
                    response["verification"].setdefault("status", "passed_with_pending_side_effect_confirmation")
                    response["verification"]["side_effect_confirmation_count"] = len(confirmations)
            return None
        report_dict = report.to_dict()
        self_check = run_payload.get("self_check") if isinstance(run_payload.get("self_check"), dict) else {}
        self_check = dict(self_check)
        self_check["verification_status"] = "failure_detected"
        self_check["failure_report_id"] = report.report_id
        self_check["failure_class"] = report.failure_class
        self_check["suggested_owner"] = report.suggested_owner
        self_check["suggested_location"] = report.suggested_location
        repair_items = self_check.get("repair_plan") if isinstance(self_check.get("repair_plan"), list) else []
        repair_items = list(repair_items)
        repair_items.append({
            "source": "verification_brain",
            "failure_report_id": report.report_id,
            "failure_class": report.failure_class,
            "suggested_owner": report.suggested_owner,
            "suggested_location": report.suggested_location,
            "evidence_path": report.evidence_path,
            "repair_plan": report.repair_plan,
        })
        self_check["repair_plan"] = repair_items
        run_payload["self_check"] = self_check
        run_payload["verification_report"] = report_dict
        run_id = str(run_payload.get("run_id") or "").strip()
        if run_id:
            try:
                self.store.write_json(f"generated/results/{run_id}.json", run_payload)
            except Exception:
                pass
        if response is not None:
            response["verification"] = {
                "status": "failure_detected",
                "failure_report_id": report.report_id,
                "failure_class": report.failure_class,
                "suggested_owner": report.suggested_owner,
                "suggested_location": report.suggested_location,
                "evidence_path": report.evidence_path,
            }
            response.setdefault("repair_plan", []).append({
                "source": "verification_brain",
                "failure_class": report.failure_class,
                "suggested_owner": report.suggested_owner,
                "suggested_location": report.suggested_location,
            })
        return report_dict


    async def execute_task(self, task_name: str | None, provided_inputs: dict[str, Any] | None = None, instruction: str | None = None) -> dict[str, Any]:
        state_run_id = str((provided_inputs or {}).get("_runtime_state_run_id") or (provided_inputs or {}).get("_state_run_id") or "studio_runtime")
        runtime_state_manager.emit(
            run_id=state_run_id,
            step_id="task.load",
            level="user",
            kind="validation",
            status="running",
            title="Task graph loading",
            message="Loading and validating the requested task graph.",
            method="json_store",
            input={"task_name": task_name},
            progress=10,
        )
        if not task_name:
            return {
                "action": "execute_task_graph",
                "origin": "auxiliary_brain",
                "status": "blocked",
                "message": "A task name is required.",
            }
        task_graph = self.store.read_json(f"generated/tasks/{task_name}.json")
        if not task_graph:
            return {
                "action": "execute_task_graph",
                "origin": "auxiliary_brain",
                "status": "not_found",
                "task_name": task_name,
            }
        runtime_state_manager.emit(run_id=state_run_id, step_id="task.load", level="developer", kind="validation", status="completed", title="Task graph loaded", message="Task graph loaded from runtime storage.", output={"task_name": task_name, "task_count": len(task_graph.get("tasks") or []) if isinstance(task_graph, dict) else 0}, progress=100)
        if self._task_instruction_changed(task_graph):
            runtime_state_manager.emit(run_id=state_run_id, step_id="task.rebuild", level="developer", kind="repair", status="running", title="Task graph rebuild", message="Instruction changed; rebuilding the task graph from current instruction.", method="instruction_workflow_planner", progress=20)
            task_graph = self._rebuild_task_graph_from_current_instruction(task_graph)
            runtime_state_manager.emit(run_id=state_run_id, step_id="task.rebuild", level="developer", kind="repair", status="completed", title="Task graph rebuilt", message="Task graph rebuild completed.", progress=100)
        provided_inputs = provided_inputs or {}
        payload_only_ids = self._execution_payload_only_ids(task_graph, provided_inputs)
        payload_only_execution = bool(payload_only_ids)
        if payload_only_ids:
            task_graph = self._task_graph_with_payload_only_participants(task_graph, payload_only_ids)
        all_participants = self.store.list_json("generated/agents")
        selected_ids = {str(x).strip() for x in (task_graph.get("selected_participant_ids") or []) if str(x).strip()}
        if selected_ids:
            participants = [p for p in all_participants if str(p.get("participant_id") or p.get("id") or "").strip() in selected_ids]
            found_ids = {str(p.get("participant_id") or p.get("id") or "").strip() for p in participants}
            missing_ids = selected_ids - found_ids
            if missing_ids:
                task_participants = self._participants_from_task_graph(task_graph, missing_ids)
                participants.extend(task_participants)
        else:
            participants = all_participants
        runtime_parameters = {}
        if isinstance(task_graph.get("runtime_parameters"), dict):
            runtime_parameters.update(task_graph.get("runtime_parameters") or {})
        runtime_parameters.update(self._extract_step_scoped_runtime_parameters_from_tasks(task_graph.get("tasks") if isinstance(task_graph.get("tasks"), list) else []))
        runtime_parameters.update(self._extract_named_parameter_blocks_from_instruction(str(task_graph.get("instruction") or ""), participants))
        runtime_parameters.update(self._extract_runtime_parameters_from_instruction(instruction or ""))
        runtime_parameters.update(self._structural_source_runtime_context(task_graph=task_graph, instruction=instruction))
        if isinstance(provided_inputs, dict):
            runtime_parameters.update({
                k: v
                for k, v in provided_inputs.items()
                if v not in (None, "", [], {}) and not str(k).startswith("_scheduled_") and str(k) not in {"_payload_only_selected_participant_ids", "_runtime_state_run_id", "_state_run_id", "_perception_package"}
            })
        runtime_state_manager.emit(run_id=state_run_id, step_id="pre_execution.parameters", level="user", kind="validation", status="running", title="Parameter preflight", message="Checking runtime parameters before execution.", method="parameter_contract", input={"known_parameter_count": len(runtime_parameters)}, progress=30)
        preflight = self._preflight_runtime_parameters(task_graph, participants, runtime_parameters)
        runtime_state_manager.emit(run_id=state_run_id, step_id="pre_execution.parameters", level="developer", kind="validation", status="waiting_input" if preflight.get("status") == "requires_input" else "completed", title="Parameter preflight result", message=str(preflight.get("status") or "completed"), output={"status": preflight.get("status"), "missing_count": len(preflight.get("missing_inputs") or [])}, progress=100)
        if preflight.get("status") == "requires_input":
            run_id = new_id("delegation_run")
            run_payload = {
                "run_id": run_id,
                "origin": "auxiliary_brain",
                "status": "requires_input",
                "task_name": str(task_graph.get("task_name") or task_graph.get("graph_id") or task_name),
                "current_stage": "waiting_for_runtime_parameters",
                "pending_action": preflight.get("pending_action"),
                "missing_inputs": preflight.get("missing_inputs") or [],
                "runtime_parameters": runtime_parameters,
                "pre_execution_parameter_analysis": preflight.get("analysis"),
                "completed_at": self._now(),
            }
            self.store.write_json(f"generated/results/{run_id}.json", run_payload)
            status = "requires_input"
            result = run_payload
        else:
            reuse_response = None
            if not payload_only_execution:
                reuse_response = await self._try_reused_task_execution(task_name, task_graph, participants, runtime_parameters)
            if reuse_response is not None:
                return reuse_response
            task_graph = dict(task_graph)
            task_graph["runtime_parameters"] = runtime_parameters
            runtime_state_manager.emit(run_id=state_run_id, step_id="execution.graph", level="user", kind="lifecycle", status="running", title="Graph execution", message="Executing the locked task graph.", method="delegation_runtime", progress=20)
            result = await self.delegation_runtime.execute_task(task_graph, participants)
            runtime_state_manager.emit(run_id=state_run_id, step_id="execution.graph", level="developer", kind="output", status=str(result.get("status") or "completed"), title="Graph execution result", message=str(result.get("status") or "completed"), output={"run_id": result.get("run_id"), "status": result.get("status")}, progress=100)
        status = result.get("status", "completed")
        if status == "completed":
            try:
                self.execution_reuse_store.register_success(task_graph=task_graph, participants=participants, run_payload=result)
            except Exception:
                pass
        response = {
            "action": "execute_task_graph",
            "origin": "auxiliary_brain",
            "status": status,
            "task_name": task_name,
            "run_id": result.get("run_id"),
            "final_answer": self._compact_final_answer((result.get("synthesis") or {}).get("final_answer")),
            "delivery": result.get("delivery"),
        }
        if status in {"requires_key", "requires_input", "paused"}:
            pending_action = result.get("pending_action")
            response["pending_action"] = pending_action
            response["missing_inputs"] = self._normalize_missing_inputs(result.get("missing_inputs", []), pending_action)
            response["interaction_request"] = {
                "type": "collect_runtime_parameters",
                "kind": str((pending_action or {}).get("kind") or "runtime_parameter_input"),
                "fields": response["missing_inputs"],
                "message": self._paused_message(response["missing_inputs"], pending_action),
            }
            response["message"] = self._paused_message(response["missing_inputs"], pending_action)
        if status in {"requires_key", "requires_input", "paused"}:
            runtime_state_manager.emit(
                run_id=state_run_id,
                step_id="result.verify",
                level="developer",
                kind="verification",
                status="paused",
                title="Result verification paused",
                message="Execution is waiting for runtime interaction; result verification will resume after continuation.",
                output={"verification": {"status": "waiting_for_runtime_interaction"}},
                progress=100,
            )
            response["verification"] = {"status": "waiting_for_runtime_interaction"}
        else:
            runtime_state_manager.emit(run_id=state_run_id, step_id="result.verify", level="user", kind="verification", status="running", title="Result verification", message="Verifying execution material and response quality.", method="verification_brain", progress=40)
            self._attach_verification_report(task_graph=task_graph, participants=participants, run_payload=result, response=response, stage="execute_task")
            runtime_state_manager.emit(run_id=state_run_id, step_id="result.verify", level="developer", kind="verification", status="completed", title="Result verification completed", message=str((response.get("verification") or {}).get("status") or "completed"), output={"verification": response.get("verification")}, progress=100)
        runtime_state_manager.emit(run_id=state_run_id, step_id="final.synthesis", level="user", kind="output", status=status, title="Final synthesis", message="Final response prepared for the user.", output={"status": status, "has_final_answer": bool(response.get("final_answer"))}, progress=100)
        return response

    async def resume_run(self, run_id: str, provided_inputs: dict[str, Any] | None = None) -> dict[str, Any]:
        run_id = (run_id or "").strip()
        if not run_id:
            return {
                "action": "resume_task_graph",
                "origin": "auxiliary_brain",
                "status": "blocked",
                "message": "A run id is required.",
            }
        run_payload = self.store.read_json(f"generated/results/{run_id}.json")
        if not run_payload:
            return {
                "action": "resume_task_graph",
                "origin": "auxiliary_brain",
                "status": "not_found",
                "run_id": run_id,
            }
        task_name = str(run_payload.get("task_name") or "").strip()
        if not task_name:
            return {
                "action": "resume_task_graph",
                "origin": "auxiliary_brain",
                "status": "blocked",
                "run_id": run_id,
                "message": "The paused run does not reference a task name.",
            }
        task_graph = self.store.read_json(f"generated/tasks/{task_name}.json")
        if not task_graph:
            return {
                "action": "resume_task_graph",
                "origin": "auxiliary_brain",
                "status": "not_found",
                "run_id": run_id,
                "task_name": task_name,
            }
        all_participants = self.store.list_json("generated/agents")
        selected_ids = set(task_graph.get("selected_participant_ids") or [])
        participants = [p for p in all_participants if p.get("participant_id") in selected_ids] or all_participants
        pending = run_payload.get("pending_action") if isinstance(run_payload.get("pending_action"), dict) else {}
        if str(pending.get("source") or "") == "execution_reuse_asset":
            runtime_parameters = {}
            if isinstance(run_payload.get("runtime_parameters"), dict):
                runtime_parameters.update(run_payload.get("runtime_parameters") or {})
            if isinstance(provided_inputs, dict):
                runtime_parameters.update({k: v for k, v in provided_inputs.items() if v not in (None, "", [], {})})
            reuse_response = await self._try_reused_task_execution(task_name, task_graph, participants, runtime_parameters)
            if reuse_response is not None:
                reuse_response["action"] = "resume_task_graph"
                reuse_response["resumed_from_run_id"] = run_id
                return reuse_response
            task_graph = dict(task_graph)
            task_graph["runtime_parameters"] = runtime_parameters
            result = await self.delegation_runtime.execute_task(task_graph, participants)
        elif str(pending.get("kind") or "") in {"studio_pre_execution_uploaded_artifact_parameters", "studio_pre_execution_runtime_parameters"}:
            runtime_parameters = {}
            if isinstance(task_graph.get("runtime_parameters"), dict):
                runtime_parameters.update(task_graph.get("runtime_parameters") or {})
            if isinstance(run_payload.get("runtime_parameters"), dict):
                runtime_parameters.update(run_payload.get("runtime_parameters") or {})
            if isinstance(provided_inputs, dict):
                runtime_parameters.update({k: v for k, v in provided_inputs.items() if v not in (None, "", [], {})})
            preflight = self._preflight_runtime_parameters(task_graph, participants, runtime_parameters)
            if preflight.get("status") == "requires_input":
                run_payload.update({
                    "status": "requires_input",
                    "current_stage": "waiting_for_runtime_parameters",
                    "pending_action": preflight.get("pending_action"),
                    "missing_inputs": preflight.get("missing_inputs") or [],
                    "runtime_parameters": runtime_parameters,
                    "completed_at": self._now(),
                })
                self.store.write_json(f"generated/results/{run_id}.json", run_payload)
                result = run_payload
            else:
                task_graph = dict(task_graph)
                task_graph["runtime_parameters"] = runtime_parameters
                result = await self.delegation_runtime.execute_task(task_graph, participants)
        else:
            result = await self.delegation_runtime.resume_task(run_payload, task_graph, participants, provided_inputs=provided_inputs)
        status = result.get("status", "completed")
        if status == "completed":
            try:
                self.execution_reuse_store.register_success(task_graph=task_graph, participants=participants, run_payload=result)
            except Exception:
                pass
        response = {
            "action": "resume_task_graph",
            "origin": "auxiliary_brain",
            "status": status,
            "task_name": task_name,
            "run_id": result.get("run_id"),
            "resumed_from_run_id": run_id,
            "final_answer": self._compact_final_answer((result.get("synthesis") or {}).get("final_answer")),
            "delivery": result.get("delivery"),
        }
        if status in {"requires_key", "requires_input", "paused"}:
            pending_action = result.get("pending_action")
            response["pending_action"] = pending_action
            response["missing_inputs"] = self._normalize_missing_inputs(result.get("missing_inputs", []), pending_action)
            response["interaction_request"] = {
                "type": "collect_runtime_parameters",
                "kind": str((pending_action or {}).get("kind") or "runtime_parameter_input"),
                "fields": response["missing_inputs"],
                "message": self._paused_message(response["missing_inputs"], pending_action),
            }
            response["message"] = self._paused_message(response["missing_inputs"], pending_action)
        self._attach_verification_report(task_graph=task_graph, participants=participants, run_payload=result, response=response, stage="resume_task")
        return response

    def _execution_payload_only_ids(self, task_graph: dict[str, Any], provided_inputs: dict[str, Any] | None) -> list[str]:
        """Return executable payload participants for control-plane task graphs.

        A saved task may contain participants that define runtime control policy
        rather than payload work.  Once that policy is materialized on the task
        graph, those controller participants must not be treated as ordinary
        executable steps during preflight or scheduled dispatch.  The rule is
        structural: it only uses the durable schedule policy and participant ids,
        not any capability, agent, or business name.
        """
        provided_inputs = provided_inputs or {}
        explicit = provided_inputs.get("_payload_only_selected_participant_ids")
        if isinstance(explicit, list):
            values = [str(x).strip() for x in explicit if str(x).strip()]
            if values:
                return values
        policy = task_graph.get("schedule_policy") if isinstance(task_graph.get("schedule_policy"), dict) else {}
        schedule_enabled = bool(policy.get("enabled"))
        dispatch_requested = bool(provided_inputs.get("_scheduled_payload_dispatch"))
        if not schedule_enabled and not dispatch_requested:
            return []
        controllers = {str(x).strip() for x in (policy.get("controller_participant_ids") or []) if str(x).strip()}
        if not controllers:
            return []
        selected = [str(x).strip() for x in (task_graph.get("selected_participant_ids") or []) if str(x).strip()]
        payload = [x for x in selected if x and x not in controllers]
        if payload:
            return payload
        tasks = task_graph.get("tasks") if isinstance(task_graph.get("tasks"), list) else []
        derived: list[str] = []
        for item in tasks:
            if not isinstance(item, dict):
                continue
            pid = str(item.get("participant_id") or "").strip()
            if pid and pid not in controllers:
                derived.append(pid)
        return derived

    def _task_graph_with_payload_only_participants(self, task_graph: dict[str, Any], payload_ids: list[str]) -> dict[str, Any]:
        payload_set = {str(x).strip() for x in payload_ids if str(x).strip()}
        graph = dict(task_graph)
        graph["selected_participant_ids"] = [x for x in (graph.get("selected_participant_ids") or []) if str(x).strip() in payload_set] or list(payload_set)
        tasks = graph.get("tasks") if isinstance(graph.get("tasks"), list) else []
        if tasks:
            graph["tasks"] = [dict(t) for t in tasks if isinstance(t, dict) and str(t.get("participant_id") or "").strip() in payload_set]
        graph["scheduled_payload_dispatch"] = True
        return graph

    def _participants_from_task_graph(self, task_graph: dict[str, Any], participant_ids: set[str]) -> list[dict[str, Any]]:
        """Rebuild task-scoped generated participants when they are not durable agents.

        The task graph is the source of truth for runtime-generated steps. If a
        task selected generated participants that are not present in the durable
        agent store, execution must not fall back to unrelated agents from the
        same community.
        """
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

    def _normalize_missing_inputs(self, missing_inputs: Any, pending_action: dict[str, Any] | None) -> list[dict[str, Any]]:
        if isinstance(missing_inputs, list) and missing_inputs:
            return [x for x in missing_inputs if isinstance(x, dict)]
        pending = pending_action if isinstance(pending_action, dict) else {}
        kind = str(pending.get("kind") or "")
        if kind in {"secret_input", "optional_credential_choice"}:
            request = pending.get("request") if isinstance(pending.get("request"), dict) else {}
            api_source = request.get("api_source") if isinstance(request.get("api_source"), dict) else {}
            api_sources = request.get("api_sources") if isinstance(request.get("api_sources"), list) else []
            secret_fields = request.get("secret_fields") if isinstance(request.get("secret_fields"), list) else []
            first_secret = secret_fields[0] if secret_fields and isinstance(secret_fields[0], dict) else {}
            provider = str(api_source.get("provider") or first_secret.get("provider") or request.get("provider") or pending.get("provider") or "credential-protected provider")
            source_url = str(api_source.get("url") or first_secret.get("source_url") or pending.get("source_url") or "")
            field_name = str(first_secret.get("name") or api_source.get("secret_key") or pending.get("secret_key") or "runtime_access_key")
            return [{
                "kind": kind,
                "field": field_name,
                "message": str(pending.get("message") or request.get("message") or "A credential-protected method is available. Enter the key to use it, or continue without this key to try another allowed method."),
                "input_type": "password",
                "required": False,
                "provider": provider,
                "source_url": source_url,
                "api_source": api_source,
                "api_sources": api_sources,
            }]
        if kind in {"collect_runtime_parameters", "runtime_parameter_input", "uploaded_artifact_parameters", "studio_pre_execution_uploaded_artifact_parameters"}:
            request = pending.get("request") if isinstance(pending.get("request"), dict) else {}
            fields = request.get("fields") if isinstance(request.get("fields"), list) else []
            normalized = []
            for index, field in enumerate(fields):
                if isinstance(field, dict):
                    normalized.append({
                        "kind": kind,
                        "field": str(field.get("field") or field.get("name") or field.get("source_field") or f"field_{index}"),
                        "label": str(field.get("label") or field.get("name") or field.get("field") or f"Input {index + 1}"),
                        "message": str(field.get("question") or field.get("prompt") or field.get("message") or field.get("description") or field.get("label") or request.get("message") or "Please provide this runtime value."),
                        "input_type": str(field.get("input_type") or field.get("type") or "text"),
                        "placeholder": str(field.get("placeholder") or ""),
                        "description": str(field.get("description") or ""),
                        "required": bool(field.get("required", True)),
                        "aliases": field.get("aliases") if isinstance(field.get("aliases"), list) else [],
                        "merge_targets": field.get("merge_targets") if isinstance(field.get("merge_targets"), list) else [],
                    })
            if normalized:
                return normalized
            return [{"kind": kind, "field": "input", "message": str(request.get("message") or pending.get("message") or "Please provide runtime values required by the uploaded artifact."), "required": True}]

        if kind == "human_information_required":
            request = pending.get("request") if isinstance(pending.get("request"), dict) else {}
            fields = request.get("fields") if isinstance(request.get("fields"), list) else []
            normalized = []
            for index, field in enumerate(fields):
                if isinstance(field, dict):
                    normalized.append({
                        "kind": kind,
                        "field": str(field.get("name") or field.get("field") or f"field_{index}"),
                        "message": str(field.get("message") or field.get("label") or "Please provide this value."),
                        "input_type": str(field.get("input_type") or "text"),
                        "required": bool(field.get("required", True)),
                    })
            if normalized:
                return normalized
            return [{"kind": kind, "field": "input", "message": str(request.get("message") or pending.get("message") or "Please provide the required information."), "required": True}]
        if kind == "validation_recovery":
            # Validation recovery should normally be handled automatically by the runtime repair/escalation path.
            # Expose a JSON editor only as a final fallback so the UI can still recover instead of silently pausing.
            return [{
                "kind": kind,
                "field": "corrected_json",
                "message": "Automatic repair could not fully validate this node result. Paste corrected JSON to continue.",
                "validation_error": str(pending.get("validation_error") or ""),
                "input_type": "textarea",
                "required": True,
            }]
        return []

    def _paused_message(self, missing_inputs: list[dict[str, Any]], pending_action: dict[str, Any] | None) -> str:
        pending = pending_action if isinstance(pending_action, dict) else {}
        kind = str(pending.get("kind") or "")
        if missing_inputs:
            return "Delegated primary-runtime execution is waiting for required input."
        if kind == "validation_recovery":
            return "Delegated primary-runtime execution paused after schema validation failed. Runtime auto repair should handle structural errors before asking the user."
        return "Delegated primary-runtime execution is paused."



    def _extract_runtime_parameters_from_instruction(self, instruction: str) -> dict[str, Any]:
        """Extract explicit task-run parameters from user-authored text.

        This parser is syntax based and domain-neutral. It accepts assignment
        material in either one-key-per-line form or compact multi-assignment
        form, including section-prefixed lines such as `Parameters: a = 1 b = 2`.
        Section headers without values remain ignored.
        """
        text = str(instruction or "")
        out: dict[str, Any] = {}
        header_prefixes = {"step", "parameters", "parameter", "params"}
        single_assignment = re.compile(r"^\s*(?:[-*]\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*(?:=|:)\s*(.+?)\s*$")
        pair_scan = re.compile(
            r"\b([A-Za-z_][A-Za-z0-9_]*)\s*(?:=|:)\s*(.*?)"
            r"(?=\s+\b[A-Za-z_][A-Za-z0-9_]*\s*(?:=|:)|\s*$)",
            flags=re.S,
        )

        def clean_value(value: Any) -> str:
            return str(value or "").strip().strip("'\"").strip()

        def add_pair(key: str, value: Any) -> None:
            key = str(key or "").strip()
            value = clean_value(value)
            if not key or not value:
                return
            lowered_key = key.casefold()
            if lowered_key in header_prefixes:
                return
            if value.endswith(":") and len(value.split()) <= 5:
                return
            out[key] = value

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            lowered = line.casefold()
            scan_line = line
            header_match = re.match(r"^\s*(?:[-*]\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$", line)
            if header_match and header_match.group(1).casefold() in header_prefixes:
                remainder = header_match.group(2).strip()
                if not remainder:
                    continue
                scan_line = remainder
            elif any(lowered.startswith(prefix + " ") for prefix in header_prefixes):
                continue

            matches = list(pair_scan.finditer(scan_line))
            if len(matches) > 1:
                for match in matches:
                    add_pair(match.group(1), match.group(2))
                continue

            match = single_assignment.match(scan_line)
            if match:
                add_pair(match.group(1), match.group(2))

        for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*(?:用|为|是)\s*([A-Za-z0-9_.:/-]+)", text, flags=re.I):
            key = match.group(1).strip()
            value = match.group(2).strip().strip("'\"")
            if key and value and key not in out:
                out[key] = value
        return out

    def _extract_step_scoped_runtime_parameters_from_tasks(self, tasks: list[dict[str, Any]]) -> dict[str, Any]:
        """Create participant-scoped runtime values from planned step fragments.

        A task instruction can contain several parameter blocks. The global
        extractor deliberately remains conservative, so this method binds values
        from each step fragment to the participant that owns the step. The
        resulting keys match AgentParameterContractService.apply_values:
        `<participant_id>.<field>`, `<participant_name>.<field>`, and a global
        `<field>` fallback when the value is unambiguous.
        """
        out: dict[str, Any] = {}
        unscoped_seen: dict[str, Any] = {}
        conflicts: set[str] = set()
        for task in tasks or []:
            if not isinstance(task, dict):
                continue
            fragment = str(task.get("source_instruction_fragment") or "")
            values = self._extract_runtime_parameters_from_instruction(fragment)
            if not values:
                continue
            pid = str(task.get("participant_id") or "").strip()
            pname = str(task.get("participant_display_name") or "").strip()
            safe_pname = re.sub(r"[^A-Za-z0-9_]+", "_", pname).strip("_")
            for key, value in values.items():
                if pid:
                    out[f"{pid}.{key}"] = value
                if pname:
                    out[f"{pname}.{key}"] = value
                if safe_pname:
                    out[f"{safe_pname}.{key}"] = value
                if key in unscoped_seen and unscoped_seen[key] != value:
                    conflicts.add(key)
                else:
                    unscoped_seen[key] = value
        for key, value in unscoped_seen.items():
            if key not in conflicts:
                out.setdefault(key, value)
        return out


    def _extract_named_parameter_blocks_from_instruction(self, instruction: str, participants: list[dict[str, Any]]) -> dict[str, Any]:
        """Extract parameter blocks addressed to a named participant.

        This is a syntax-only, domain-neutral binding pass for task text such as
        ``Parameters for <participant>:`` followed by assignment lines.  It does
        not know what any field means; it only scopes declared key/value pairs
        to the participant whose durable name/id matches the block label.
        """
        text = str(instruction or "")
        if not text.strip() or not participants:
            return {}
        participant_aliases: dict[str, dict[str, Any]] = {}
        for participant in participants or []:
            if not isinstance(participant, dict):
                continue
            aliases = [
                participant.get("participant_id"),
                participant.get("id"),
                participant.get("display_name"),
                participant.get("participant_display_name"),
                participant.get("agent_name"),
                participant.get("name"),
                participant.get("role_name"),
            ]
            for alias in aliases:
                key = self._normalize_parameter_block_target(alias)
                if key:
                    participant_aliases.setdefault(key, participant)
        if not participant_aliases:
            return {}

        out: dict[str, Any] = {}
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            header = re.match(r"^\s*(?:[-*]\s*)?parameters\s+for\s+(.+?)\s*:\s*$", line, flags=re.I)
            if not header:
                i += 1
                continue
            target_text = header.group(1).strip()
            participant = self._match_parameter_block_participant(target_text, participant_aliases)
            block_lines: list[str] = []
            i += 1
            while i < len(lines):
                current = lines[i]
                stripped = current.strip()
                if re.match(r"^\s*(?:[-*]\s*)?parameters\s+for\s+.+?:\s*$", stripped, flags=re.I):
                    break
                if re.match(r"^\s*step\s+\d+\s*:\s*$", stripped, flags=re.I):
                    break
                if re.match(r"^\s*call\s+.+", stripped, flags=re.I):
                    break
                if stripped:
                    block_lines.append(current)
                i += 1
            if participant and block_lines:
                values = self._extract_runtime_parameters_from_instruction("\n".join(block_lines))
                if values:
                    self._write_scoped_parameter_values(out, participant, values)
            continue
        return out

    def _normalize_parameter_block_target(self, value: Any) -> str:
        text = str(value or "").strip().casefold()
        if not text:
            return ""
        text = re.sub(r"[^a-z0-9_]+", "_", text)
        return text.strip("_")

    def _match_parameter_block_participant(self, target_text: str, participant_aliases: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
        target = self._normalize_parameter_block_target(target_text)
        if not target:
            return None
        if target in participant_aliases:
            return participant_aliases[target]
        # Allow harmless suffix/prefix differences caused by display labels.
        for alias, participant in participant_aliases.items():
            if alias and (alias in target or target in alias):
                return participant
        return None

    def _write_scoped_parameter_values(self, out: dict[str, Any], participant: dict[str, Any], values: dict[str, Any]) -> None:
        pid = str(participant.get("participant_id") or participant.get("id") or "").strip()
        names = [
            str(participant.get("display_name") or "").strip(),
            str(participant.get("participant_display_name") or "").strip(),
            str(participant.get("agent_name") or "").strip(),
            str(participant.get("name") or "").strip(),
        ]
        safe_names = [re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_") for name in names if name]
        for key, value in (values or {}).items():
            if value in (None, "", [], {}):
                continue
            if pid:
                out[f"{pid}.{key}"] = value
                out[f"{pid}_{key}"] = value
            for prefix in names + safe_names:
                if prefix:
                    out[f"{prefix}.{key}"] = value
                    out[f"{prefix}_{key}"] = value
            # Plain key is safe only when it is not already bound differently.
            if key not in out:
                out[key] = value
            elif out.get(key) == value:
                out[key] = value

    def _preflight_runtime_parameters(self, task_graph: dict[str, Any], participants: list[dict[str, Any]], runtime_parameters: dict[str, Any]) -> dict[str, Any]:
        """Resolve pre-execution requirements through typed context layers.

        The UI still receives one consolidated form, but internal state stays
        separated as execution inputs, resource bindings, and execution
        policies.  This prevents uploaded resources or reuse policy metadata
        from being treated as callable parameters while keeping current task
        execution behavior unchanged.
        """
        resolution_context = self._build_preflight_resolution_context(task_graph, participants, runtime_parameters)
        if resolution_context.requires_input:
            fields = resolution_context.missing_input_fields
            return {
                "status": "requires_input",
                "missing_inputs": fields,
                "analysis": resolution_context.to_analysis(),
                "pending_action": {
                    "kind": "studio_pre_execution_runtime_parameters",
                    "message": "Runtime parameter values are required before task execution.",
                    "request": {
                        "input_mode": "form",
                        "fields": fields,
                        "resolution_layers": ["input_resolution", "resource_binding", "execution_policy_resolution"],
                    },
                },
            }
        return {"status": "ready", "analysis": resolution_context.to_analysis()}

    def _build_preflight_resolution_context(self, task_graph: dict[str, Any], participants: list[dict[str, Any]], runtime_parameters: dict[str, Any]) -> PreflightResolutionContext:
        artifact_preflight = self._preflight_uploaded_artifact_parameters(task_graph, participants, runtime_parameters)
        resource_reports: list[dict[str, Any]] = []
        if isinstance(artifact_preflight.get("analysis"), list):
            resource_reports.extend([x for x in artifact_preflight.get("analysis") or [] if isinstance(x, dict)])

        resource_missing: list[dict[str, Any]] = []
        if artifact_preflight.get("status") == "requires_input":
            for field in artifact_preflight.get("missing_inputs") or []:
                if isinstance(field, dict):
                    tagged = dict(field)
                    tagged.setdefault("resolution_layer", "resource_binding")
                    resource_missing.append(tagged)
        if resource_missing or resource_reports:
            resource_reports.append({
                "source": "uploaded_artifact_contract",
                "missing_inputs": resource_missing,
                "bound_resources": self._collect_bound_resource_refs(task_graph, participants),
                "execution_policies": {},
            })

        selected = self.delegation_runtime._fresh_task_participants(
            self.delegation_runtime._select_participants(task_graph, participants)
        )
        self.delegation_runtime._apply_task_runtime_parameters_to_selected(selected, runtime_parameters)
        task_mind_graph = self.delegation_runtime._build_task_mind_graph(task_graph, selected)
        dependency_plan = (task_mind_graph.get("agent_relation_analysis") or {}) if isinstance(task_mind_graph, dict) else {}
        if not dependency_plan:
            dependency_plan = self.delegation_runtime._build_participant_dependency_plan(task_graph, selected)
        agent_fields: list[dict[str, Any]] = []
        for field in self.delegation_runtime._collect_missing_agent_parameter_fields(selected, dependency_plan=dependency_plan):
            if isinstance(field, dict):
                tagged = dict(field)
                tagged.setdefault("resolution_layer", "execution_input")
                agent_fields.append(tagged)

        return self.parameter_resolution_pipeline.build_context(
            runtime_inputs=runtime_parameters,
            resource_reports=resource_reports,
            agent_fields=agent_fields,
            policy_values=self._collect_execution_policy_values(task_graph),
            bound_resources=self._collect_bound_resource_refs(task_graph, participants),
        )

    def _collect_bound_resource_refs(self, task_graph: dict[str, Any], participants: list[dict[str, Any]]) -> dict[str, Any]:
        resources: dict[str, Any] = {}
        task_artifacts = task_graph.get("uploaded_artifacts") if isinstance(task_graph.get("uploaded_artifacts"), list) else []
        if task_artifacts:
            resources["task_uploaded_artifacts"] = task_artifacts
        participant_resources = []
        for participant in participants or []:
            if not isinstance(participant, dict):
                continue
            refs = participant.get("uploaded_artifacts") if isinstance(participant.get("uploaded_artifacts"), list) else []
            if refs:
                participant_resources.append({
                    "participant_id": participant.get("participant_id"),
                    "resources": refs,
                })
        if participant_resources:
            resources["participant_uploaded_artifacts"] = participant_resources
        return resources

    def _collect_execution_policy_values(self, task_graph: dict[str, Any]) -> dict[str, Any]:
        policy: dict[str, Any] = {}
        for key in ("execution_policy", "final_synthesis_owner"):
            value = task_graph.get(key) if isinstance(task_graph, dict) else None
            if value not in (None, "", [], {}):
                policy[key] = value
        return policy

    def _runtime_field_key(self, field: dict[str, Any]) -> str:
        return self.parameter_resolution_pipeline.field_key(field)

    def _preflight_uploaded_artifact_parameters(self, task_graph: dict[str, Any], participants: list[dict[str, Any]], runtime_parameters: dict[str, Any]) -> dict[str, Any]:
        """Inspect uploaded artifacts before delegating execution.

        Uploaded-file callable parameters are collected before primary runtime
        execution starts. Task-authored values may use the agent contract names
        while the uploaded artifact exposes lower-level callable names.  The
        bridge below resolves those run-scoped values before deciding that user
        input is missing; it never stores task values back to the agent profile.
        """
        all_missing: list[dict[str, Any]] = []
        analyses: list[dict[str, Any]] = []
        for participant in participants:
            artifacts = participant.get("uploaded_artifacts") or task_graph.get("uploaded_artifacts") or []
            if not artifacts:
                continue
            effective_parameters = dict(runtime_parameters or {})
            # Run a first inspection to learn the artifact callable contract,
            # then enrich the run parameters with safe task/agent scoped values.
            first_contract = self._build_uploaded_artifact_contract(
                task_graph=task_graph, participant=participant, artifacts=artifacts, runtime_parameters=effective_parameters
            )
            effective_parameters.update(
                self._resolve_uploaded_artifact_parameter_aliases(
                    participant=participant,
                    runtime_parameters=effective_parameters,
                    contract=first_contract,
                )
            )
            contract = self._build_uploaded_artifact_contract(
                task_graph=task_graph, participant=participant, artifacts=artifacts, runtime_parameters=effective_parameters
            )
            analyses.append(contract)
            for field in contract.get("missing_parameter_fields") or []:
                if not isinstance(field, dict):
                    continue
                # Optional artifact fields must not block task execution.  They
                # may be provided when present, but should not create repeated
                # prompts once required values have been resolved.
                if field.get("required") is False:
                    continue
                tagged = dict(field)
                tagged.setdefault("resolution_layer", "resource_binding")
                all_missing.append(tagged)
            # Persist only the additional effective bindings into this task run
            # so the later primary runtime receives the callable's exact names.
            for k, v in effective_parameters.items():
                if k not in runtime_parameters and v not in (None, "", [], {}):
                    runtime_parameters[k] = v
        # Deduplicate fields by normalized name.
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for field in all_missing:
            key = str(field.get("field") or field.get("name") or "").strip().casefold()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(field)
        if deduped:
            return {
                "status": "requires_input",
                "missing_inputs": deduped,
                "analysis": analyses,
                "pending_action": {
                    "kind": "studio_pre_execution_uploaded_artifact_parameters",
                    "message": "Uploaded artifact parameters are required before task execution.",
                    "request": {
                        "input_mode": "form",
                        "fields": deduped,
                    },
                },
            }
        return {"status": "ready", "analysis": analyses}

    def _build_uploaded_artifact_contract(self, *, task_graph: dict[str, Any], participant: dict[str, Any], artifacts: list[dict[str, Any]], runtime_parameters: dict[str, Any]) -> dict[str, Any]:
        step = {
            "step_id": "studio_pre_execution_uploaded_artifact",
            "execution_method": "uploaded_artifact",
            "action_type": "use_uploaded_file",
            "uploaded_artifacts": artifacts,
            "parameters": runtime_parameters,
            "runtime_parameters": runtime_parameters,
            "objective": participant.get("execution_objective") or participant.get("instruction") or task_graph.get("instruction") or "",
        }
        state = {
            "run_id": "studio_pre_execution",
            "input": task_graph.get("instruction") or "",
            "runtime_parameters": runtime_parameters,
            "provided_inputs": runtime_parameters,
            "runtime_context": {
                "uploaded_artifacts": artifacts,
                "available_artifacts": artifacts,
                "agent_parameters": {"values": runtime_parameters},
            },
            "results": {
                "context_awareness": {
                    "clean_context": {
                        "uploaded_artifacts": artifacts,
                        "available_artifacts": artifacts,
                        "known_parameters": runtime_parameters,
                    }
                }
            },
        }
        return self.uploaded_artifact_contract.build_contract(state=state, step=step, step_id="step_1")

    def _resolve_uploaded_artifact_parameter_aliases(self, *, participant: dict[str, Any], runtime_parameters: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
        """Map task/agent scoped values onto uploaded callable field names.

        This is a generic bridge: exact/normalized aliases win first, then a
        conservative one-to-one fallback maps a single unresolved required
        callable field to a single provided participant value.  Optional fields
        are filled only when a compatible provided field name exists.
        """
        selected = contract.get("selected_artifact") if isinstance(contract.get("selected_artifact"), dict) else {}
        input_contract = selected.get("input_contract") if isinstance(selected.get("input_contract"), dict) else {}
        properties = input_contract.get("properties") if isinstance(input_contract.get("properties"), dict) else {}
        if not properties:
            return {}
        required = {str(x) for x in input_contract.get("required", []) if str(x).strip()} if isinstance(input_contract.get("required"), list) else set()
        participant_values = self._participant_scoped_runtime_values(participant, runtime_parameters)
        additions: dict[str, Any] = {}
        used_source_keys: set[str] = set()
        for field_name in properties.keys():
            if self._value_present_for_field(field_name, {**runtime_parameters, **additions}):
                continue
            matched_key = self._best_runtime_value_key_for_field(field_name, participant_values)
            if matched_key:
                additions[str(field_name)] = participant_values[matched_key]
                used_source_keys.add(matched_key)
        unresolved_required = [name for name in required if not self._value_present_for_field(name, {**runtime_parameters, **additions})]
        if len(unresolved_required) == 1:
            candidates = [k for k, v in participant_values.items() if k not in used_source_keys and v not in (None, "", [], {})]
            if len(candidates) == 1:
                additions[unresolved_required[0]] = participant_values[candidates[0]]
        return additions

    def _participant_scoped_runtime_values(self, participant: dict[str, Any], runtime_parameters: dict[str, Any]) -> dict[str, Any]:
        pid = str(participant.get("participant_id") or "").strip()
        names = [str(participant.get(k) or "").strip() for k in ("display_name", "agent_name", "name", "role_name")]
        safe_names = [re.sub(r"[^A-Za-z0-9_]+", "_", n).strip("_") for n in names if n]
        prefixes = [x for x in [pid, *names, *safe_names] if x]
        out: dict[str, Any] = {}
        for key, value in (runtime_parameters or {}).items():
            skey = str(key)
            for prefix in prefixes:
                dot = prefix + "."
                under = prefix + "_"
                if skey.startswith(dot):
                    out[skey[len(dot):]] = value
                elif skey.startswith(under):
                    out[skey[len(under):]] = value
        contract = participant.get("parameter_contract") if isinstance(participant.get("parameter_contract"), dict) else {}
        contract_names: set[str] = set()
        for param in contract.get("parameters") if isinstance(contract.get("parameters"), list) else []:
            if not isinstance(param, dict):
                continue
            name = str(param.get("name") or "").strip()
            if name:
                contract_names.add(name)
                if name in runtime_parameters:
                    out.setdefault(name, runtime_parameters[name])
        # Unscoped task values are safe for this participant only when they
        # match this participant's declared parameter names.  This prevents a
        # downstream agent's values from being consumed by an uploaded artifact
        # owned by a different participant.
        for key, value in (runtime_parameters or {}).items():
            skey = str(key)
            if "." not in skey and skey in contract_names and skey not in out:
                out[skey] = value
        return {k: v for k, v in out.items() if v not in (None, "", [], {})}

    def _best_runtime_value_key_for_field(self, field_name: str, values: dict[str, Any]) -> str:
        target = self._runtime_field_tokens(field_name)
        target_norm = self._runtime_field_norm(field_name)
        best_key = ""
        best_score = 0
        for key in values.keys():
            norm = self._runtime_field_norm(key)
            tokens = self._runtime_field_tokens(key)
            score = 0
            if norm == target_norm:
                score = 100
            elif norm in target_norm or target_norm in norm:
                score = 60
            else:
                overlap = target & tokens
                if overlap:
                    score = 20 + len(overlap) * 10
            if score > best_score:
                best_key = key
                best_score = score
        return best_key if best_score >= 30 else ""

    def _value_present_for_field(self, field_name: str, values: dict[str, Any]) -> bool:
        target_norm = self._runtime_field_norm(field_name)
        for key, value in (values or {}).items():
            if value in (None, "", [], {}):
                continue
            if self._runtime_field_norm(key) == target_norm:
                return True
        return False

    def _runtime_field_norm(self, value: Any) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())

    def _runtime_field_tokens(self, value: Any) -> set[str]:
        raw = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(value or ""))
        tokens = {t for t in re.split(r"[^A-Za-z0-9]+", raw.casefold()) if t}
        generic = {"str", "string", "text", "value", "val", "name", "id", "input", "param", "parameter"}
        return {t for t in tokens if t not in generic}

    def _derive_execution_objective(self, instruction: str, participant_name: str | None = None) -> str:
        """Extract the participant's reusable work objective from a creation command.

        The studio stores both the original definition command and the runtime
        objective. Delegated execution must use the objective, not the creation
        sentence, otherwise the primary runtime may plan to create an agent again.
        This parser is generic command-shape handling; it does not encode any
        business domain.
        """
        text = (instruction or "").strip()
        if not text:
            return ""

        # Common shape: "create ... named <name> to <objective>".
        match = re.search(
            r"\bnamed\s+.+?\s+to\s+(.+?)(?:[。.!?]\s*)?$",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match:
            return match.group(1).strip(" .。")

        # Common shape without a name: "create ... to <objective>".
        match = re.search(
            r"\bcreate\b.+?\bto\s+(.+?)(?:[。.!?]\s*)?$",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match:
            return match.group(1).strip(" .。")

        # If the task statement used a relative clause, keep the clause body.
        match = re.search(
            r"\bthat\s+(.+?)(?:[。.!?]\s*)?$",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match:
            return match.group(1).strip(" .。")

        return text



    def _resolve_uploaded_artifacts_for_instruction(self, instruction: str, uploaded_artifacts: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        """Bind explicit UI artifacts and filename references in the instruction.

        This is a generic artifact-reference resolver. It does not decide the
        domain or action result. It only converts user-visible filenames or
        artifact ids into registered artifact records so ai_core can plan the
        fixed use_uploaded_file action.
        """
        return self.artifact_registry.bind_for_instruction(instruction, uploaded_artifacts or [])

    def _normalize_uploaded_artifacts(self, uploaded_artifacts: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        return self.artifact_registry.normalize_records(uploaded_artifacts or [])

    def _parameter_contract_schema_only(self, parameter_contract: dict[str, Any]) -> dict[str, Any]:
        """Store only parameter schema on the agent profile.

        Values are task-run state and must be collected again on every execution.
        """
        import copy
        contract = copy.deepcopy(parameter_contract) if isinstance(parameter_contract, dict) else {}
        params = contract.get("parameters") if isinstance(contract.get("parameters"), list) else []
        for param in params:
            if isinstance(param, dict):
                param["values"] = []
        contract["missing_information"] = [p for p in params if isinstance(p, dict) and p.get("required", True)]
        return contract

    def _runtime_parameters_from_contract(self, parameter_contract: dict[str, Any]) -> dict[str, list[Any]]:
        params = parameter_contract.get("parameters") if isinstance(parameter_contract, dict) else []
        out: dict[str, list[Any]] = {}
        if not isinstance(params, list):
            return out
        for param in params:
            if not isinstance(param, dict):
                continue
            name = str(param.get("name") or "").strip()
            values = param.get("values") if isinstance(param.get("values"), list) else []
            if name and values:
                out[name] = values
        return out

    def _ensure_community(self) -> str:
        existing = self.store.list_json("generated/communities")
        if existing:
            return str(existing[0].get("community_id") or existing[0].get("id") or "community")
        community_id = new_id("community")
        payload = {
            "community_id": community_id,
            "origin": "auxiliary_brain",
            "status": "created",
            "created_at": self._now(),
            "participants_path": "runtime/generated/agents",
            "tasks_path": "runtime/generated/tasks",
        }
        self.store.write_json(f"generated/communities/{community_id}.json", payload)
        return community_id

    def _update_community(self) -> None:
        payload = {
            "community_id": self.community_id,
            "origin": "auxiliary_brain",
            "status": "active",
            "updated_at": self._now(),
            "participants_count": len(self.store.list_json("generated/agents")),
            "tasks_count": len(self.store.list_json("generated/tasks")),
        }
        self.store.write_json(f"generated/communities/{self.community_id}.json", payload)
        trace = {
            "trace_id": new_id("trace"),
            "origin": "auxiliary_brain",
            "community_id": self.community_id,
            "updated_at": self._now(),
            "paths": {
                "participants": "runtime/generated/agents",
                "tasks": "runtime/generated/tasks",
                "communities": "runtime/generated/communities",
            },
        }
        self.store.write_json(f"traces/agent_delegation/{trace['trace_id']}.json", trace)

    def _select_participants_for_instruction(self, instruction: str, participants: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not participants:
            return []
        text = instruction.casefold()
        selected = []
        for participant in participants:
            name = str(participant.get("name") or participant.get("agent_name") or "").casefold()
            pid = str(participant.get("participant_id") or "").casefold()
            if name and name in text:
                selected.append(participant)
            elif pid and pid in text:
                selected.append(participant)
        return self._dedupe_selected_participants(selected or participants)

    def _dedupe_selected_participants(self, participants: list[dict[str, Any]]) -> list[dict[str, Any]]:
        chosen: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for participant in participants:
            if not isinstance(participant, dict):
                continue
            key = self._participant_reuse_key(participant)
            if not key:
                key = str(participant.get("participant_id") or len(order))
            current = chosen.get(key)
            if current is None:
                chosen[key] = participant
                order.append(key)
            elif str(participant.get("created_at") or "") >= str(current.get("created_at") or ""):
                chosen[key] = participant
        return [chosen[k] for k in order if k in chosen]

    def _participant_reuse_key(self, participant: dict[str, Any]) -> str:
        name = str(participant.get("name") or participant.get("agent_name") or participant.get("display_name") or "").strip().casefold()
        objective = str(participant.get("execution_objective") or participant.get("instruction") or "").strip().casefold()
        objective = re.sub(r"\s+", " ", objective)[:180]
        artifacts = participant.get("uploaded_artifacts") if isinstance(participant.get("uploaded_artifacts"), list) else []
        artifact_sig = ",".join(sorted(str(a.get("artifact_id") or a.get("path") or a.get("filename") or "") for a in artifacts if isinstance(a, dict)))
        return "|".join(part for part in (name, objective, artifact_sig) if part)


    def _derive_execution_controller_participant_ids(self, *, tasks: list[dict[str, Any]], participants: list[dict[str, Any]], runtime_parameters: dict[str, Any]) -> list[str]:
        """Identify task participants that only define durable execution timing.

        The rule is structural: a controller step is the step whose source
        fragment declares timing policy fields. It does not depend on any
        concrete business capability, message type, recipient, provider, or tool.
        """
        participant_ids = {str(p.get("participant_id") or p.get("id") or "").strip() for p in participants if isinstance(p, dict)}
        participant_ids.discard("")
        controller_ids: list[str] = []
        timing_keys = {"interval", "interval_seconds", "every", "repeat", "repeat_every"}
        for task in tasks or []:
            if not isinstance(task, dict):
                continue
            pid = str(task.get("participant_id") or task.get("participant") or task.get("agent_id") or "").strip()
            if not pid or pid not in participant_ids:
                continue
            fragment = str(task.get("source_instruction_fragment") or task.get("objective") or "")
            values = self._extract_runtime_parameters_from_instruction(fragment)
            normalized_keys = {str(k).casefold() for k in values.keys()}
            has_timing_assignment = bool(normalized_keys & timing_keys)
            has_timing_phrase = bool(self._extract_generic_interval_seconds(fragment))
            if has_timing_assignment or has_timing_phrase:
                if pid not in controller_ids:
                    controller_ids.append(pid)
        return controller_ids

    def _emit_schedule_observation(self, event: str, *, task_name: str, data: dict[str, Any] | None = None) -> None:
        """Write operator-visible scheduler observations without affecting execution."""
        payload = {"event": event, "task_name": task_name, **(data or {})}
        try:
            from ai_core.runtime.observability.runtime_console import emit_console_event
            emit_console_event(area="scheduler", event=event, status="info", message=event, data=payload)
        except Exception:
            pass
        try:
            from datetime import datetime, timezone
            trace_dir = Path("runtime") / "traces" / "scheduled_tasks"
            trace_dir.mkdir(parents=True, exist_ok=True)
            with (trace_dir / "scheduler.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(), **payload}, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _extract_schedule_policy_from_instruction(self, instruction: str) -> dict[str, Any]:
        """Extract a generic durable execution policy from user language.

        This is intentionally capability-agnostic. It does not know what the
        task does and it does not inject any domain behavior. It only recognizes
        that the task graph itself should be executed repeatedly or once later.
        """
        text = str(instruction or "")
        lower = text.casefold()
        if not any(token in lower for token in ("execution policy", "repeat", "every", "run every", "once at", "schedule")):
            return {"enabled": False, "mode": "none"}
        interval_seconds = self._extract_generic_interval_seconds(text)
        if interval_seconds:
            return {
                "enabled": True,
                "mode": "recurring",
                "interval_seconds": interval_seconds,
                "next_run_at": self._now(),
                "created_at": self._now(),
                "source": "user_declared_execution_policy",
            }
        return {"enabled": False, "mode": "unresolved", "source": "user_declared_execution_policy"}

    def _extract_generic_interval_seconds(self, text: str) -> int | None:
        patterns = [
            r"(?:repeat|run)\s+every\s+(\d+)\s*(seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h)",
            r"every\s+(\d+)\s*(seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h)",
            r"interval\s*[:=]\s*(\d+)\s*(seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h)",
        ]
        for pattern in patterns:
            m = re.search(pattern, text, flags=re.IGNORECASE)
            if not m:
                continue
            value = int(m.group(1))
            unit = m.group(2).casefold()
            if unit in {"s", "sec", "secs", "second", "seconds"}:
                return max(1, value)
            if unit in {"m", "min", "mins", "minute", "minutes"}:
                return max(1, value * 60)
            if unit in {"h", "hr", "hrs", "hour", "hours"}:
                return max(1, value * 3600)
        if re.search(r"every\s+an?\s+hour", text, flags=re.IGNORECASE):
            return 3600
        return None

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
