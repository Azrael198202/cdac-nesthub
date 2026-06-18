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
from auxiliary_brain.runtime_tools.runtime_registered_tool_service import RuntimeRegisteredToolService
from ai_core.runtime.modeling.model_runtime_preflight import ModelRuntimePreflight
from auxiliary_brain.parameters.agent_parameter_contract import AgentParameterContractService
from auxiliary_brain.artifacts.artifact_registry import UploadedArtifactRegistry
from auxiliary_brain.artifacts.uploaded_artifact_contract import UploadedArtifactContractBuilder
from auxiliary_brain.artifacts.artifact_edit_service import ArtifactEditService
from ai_core.commands import CommandSetService
from ai_core.capabilities.capability_dispatcher import CapabilityDispatcher
from auxiliary_brain.media import ImageGenerationService, VideoGenerationService
from auxiliary_brain.media.video_generation_setup_wizard import VideoGenerationSetupWizard
from ai_core.context.execution_reuse_store import ExecutionReuseStore
from ai_core.execution.parameter_resolution import ParameterResolutionPipeline, PreflightResolutionContext
from auxiliary_brain.studio.instruction_workflow_planner import InstructionWorkflowPlanner
from auxiliary_brain.studio.structural_step_planner import StructuralStepPlanner
from auxiliary_brain.studio.runtime_semantic_planner import RuntimeSemanticPlanner
from auxiliary_brain.runtime.capability.registered_tool_agent_binder import RegisteredToolAgentBinder
from auxiliary_brain.runtime.capability.python_file_capability_importer import PythonFileCapabilityImporter
from verification_brain import RuntimeVerificationFoundation
from presentation_brain import FailureMessageRenderer, PresentationProfileRegistry
from ai_core.runtime.state import runtime_state_manager
from auxiliary_brain.task_compiler import TaskGraphCompiler, CompiledTaskLoader
from auxiliary_brain.runtime.execution.reuse_policy import ExecutionReusePolicyClassifier, COMPILED_DIRECT


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
        self.python_file_capability_importer = PythonFileCapabilityImporter()
        self.verification_foundation = RuntimeVerificationFoundation()
        self.task_graph_compiler = TaskGraphCompiler()
        self.compiled_task_loader = CompiledTaskLoader()
        self.execution_reuse_policy_classifier = ExecutionReusePolicyClassifier()
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
        if routed.action == "pause_task":
            return self.pause_task_schedule(routed.name)
        if routed.action == "resume_task":
            return self.resume_task_schedule(routed.name)
        if routed.action == "run_task_now":
            return await self.run_task_now(routed.name, provided_inputs=provided_inputs, instruction=message)

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

    def _task_graph_allows_execution_reuse(self, task_graph: dict[str, Any], participants: list[dict[str, Any]]) -> bool:
        """Return True only for structurally safe reusable-asset execution.

        Reuse is a fast path for a single previously verified executable asset.
        A saved graph with multiple participants or registered runtime tools must
        be executed through the delegation graph every time, because reusing an
        old asset can skip downstream nodes and silently bypass side effects.
        This check is structural and does not depend on business names.
        """
        if not isinstance(task_graph, dict):
            return False
        tasks = [item for item in (task_graph.get("tasks") or []) if isinstance(item, dict)]
        selected_ids = [str(x).strip() for x in (task_graph.get("selected_participant_ids") or []) if str(x).strip()]
        if len(tasks) > 1 or len(selected_ids) > 1 or len(participants or []) > 1:
            return False
        for participant in participants or []:
            profile = participant.get("capability_profile") if isinstance(participant, dict) and isinstance(participant.get("capability_profile"), dict) else {}
            if str(profile.get("capability_type") or "") == "runtime_registered_tool":
                return False
        for step in tasks:
            profile = step.get("capability_profile") if isinstance(step.get("capability_profile"), dict) else {}
            if str(profile.get("capability_type") or "") == "runtime_registered_tool":
                return False
            deps = step.get("depends_on") or step.get("dependencies") or []
            if isinstance(deps, list) and deps:
                return False
        return True

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

    def _sanitize_task_name_for_lookup(self, task_name: str | None) -> str:
        """Normalize a user supplied task name without changing stored ids.

        Natural commands often include trailing punctuation, for example
        ``Pause task TaskA.``.  Lifecycle operations must address the durable
        task record, so lookup strips only command punctuation/quotes while
        preserving the task id itself.
        """
        text = str(task_name or "").strip()
        return text.strip().strip('\"\'`').rstrip('.,;:!？。')

    def _task_graph_storage_candidates(self, task_name: str | None) -> list[tuple[str, Path]]:
        """Return durable storage candidates for legacy and compiled task graphs.

        Compiled tasks are stored under generated/tasks/<task_id>/source_task_graph.json
        while legacy tasks are stored under generated/tasks/<task_id>.json.  Schedule
        lifecycle operations must address the task instance, not any schedule agent or
        generated participant, so every lookup goes through this task-name based
        storage resolver.
        """
        candidate = self._sanitize_task_name_for_lookup(task_name)
        root = Path(getattr(self.store, "root", "runtime")) / "generated" / "tasks"
        out: list[tuple[str, Path]] = []
        if candidate:
            # Compiled task directories are the execution authority.  Check them
            # before legacy flat records so pause/resume changes affect the same
            # record the scheduler scans.
            out.append((candidate, root / candidate / "source_task_graph.json"))
            out.append((candidate, root / f"{candidate}.json"))
        try:
            for path in root.glob("*/source_task_graph.json"):
                out.append((path.parent.name, path))
            for path in root.glob("*.json"):
                out.append((path.stem, path))
        except Exception:
            pass
        seen: set[str] = set()
        unique: list[tuple[str, Path]] = []
        for name, path in out:
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            unique.append((name, path))
        return unique

    def _read_task_graph_record(self, task_name: str | None) -> tuple[str | None, dict[str, Any], Path | None]:
        candidate = self._sanitize_task_name_for_lookup(task_name)
        folded = candidate.casefold()
        fallback: tuple[str | None, dict[str, Any], Path | None] = (None, {}, None)
        for storage_name, path in self._task_graph_storage_candidates(candidate):
            if not path.exists() or not path.is_file():
                continue
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(loaded, dict):
                continue
            declared = str(loaded.get("task_name") or loaded.get("graph_id") or storage_name or "").strip()
            if not fallback[1]:
                fallback = (declared or storage_name, loaded, path)
            if not candidate:
                continue
            if candidate == declared or candidate == storage_name:
                return declared or storage_name, loaded, path
            if folded and (declared.casefold() == folded or storage_name.casefold() == folded):
                return declared or storage_name, loaded, path
            if folded and (declared.casefold().endswith(folded) or storage_name.casefold().endswith(folded)):
                return declared or storage_name, loaded, path
        if candidate:
            return candidate, {}, None
        return fallback

    def _write_task_graph_record(self, task_name: str, task_graph: dict[str, Any], path: Path | None = None) -> Path:
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(task_graph, ensure_ascii=False, indent=2), encoding="utf-8")
            return path
        return self.store.write_json(f"generated/tasks/{task_name}.json", task_graph)

    def _resolve_task_name(self, task_name: str | None) -> str | None:
        candidate = str(task_name or "").strip()
        resolved, graph, _path = self._read_task_graph_record(candidate)
        if graph and resolved:
            return resolved
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
        lookup_name = self._sanitize_task_name_for_lookup(task_name)
        resolved, graph, graph_path = self._read_task_graph_record(lookup_name)
        resolved = resolved or lookup_name
        if not resolved:
            return {"ok": False, "status": "failed", "error": {"code": "missing_task_name", "message": "A task name is required."}}
        if not graph:
            return {"ok": False, "status": "not_found", "task_name": resolved}
        policy = self._task_schedule_policy(graph)
        if str(policy.get("mode") or "none") in {"", "none"} or self._task_execution_type(graph) != "scheduled":
            return {"ok": False, "status": "not_scheduled", "task_name": resolved, "message": "The selected task is a one-shot task and does not declare a durable schedule policy."}
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
        policy.setdefault("schedule_instance_id", str(graph.get("schedule_instance_id") or f"schedule_{resolved}"))
        policy["lifecycle_key"] = str(policy.get("schedule_instance_id") or f"schedule_{resolved}")
        graph["schedule_policy"] = policy
        graph["schedule_instance_id"] = policy.get("schedule_instance_id")
        graph["updated_at"] = now
        written_paths: list[str] = []
        primary_path = self._write_task_graph_record(resolved, graph, graph_path)
        written_paths.append(str(primary_path))
        # Keep legacy and compiled task records in sync when both exist.  Older
        # UI paths may read the flat record while the scheduler scans the
        # compiled source_task_graph.json.  Lifecycle state is task-level state,
        # so mirroring it prevents pause/resume from appearing successful while
        # the active scheduler record remains enabled.
        for storage_name, candidate_path in self._task_graph_storage_candidates(resolved):
            if not candidate_path.exists() or str(candidate_path) in written_paths:
                continue
            try:
                other = json.loads(candidate_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(other, dict):
                continue
            declared = str(other.get("task_name") or other.get("graph_id") or storage_name or "").strip()
            if declared.casefold() != str(resolved).casefold() and storage_name.casefold() != str(resolved).casefold():
                continue
            other_policy = self._task_schedule_policy(other)
            if str(other_policy.get("mode") or "none") in {"", "none"}:
                continue
            other_policy.update(policy)
            other["schedule_policy"] = other_policy
            other["schedule_instance_id"] = policy.get("schedule_instance_id")
            other["updated_at"] = now
            try:
                candidate_path.write_text(json.dumps(other, ensure_ascii=False, indent=2), encoding="utf-8")
                written_paths.append(str(candidate_path))
            except Exception:
                pass
        self._emit_schedule_observation("schedule_resumed" if enabled else "schedule_paused", task_name=resolved, data={"enabled": bool(enabled), "state": policy.get("state"), "schedule_instance_id": policy.get("schedule_instance_id"), "updated_records": written_paths})
        return {"ok": True, "status": "resumed" if enabled else "paused", "task_name": resolved, "schedule_policy": policy, "updated_records": written_paths}

    def pause_task_schedule(self, task_name: str | None) -> dict[str, Any]:
        result = self.set_task_schedule_enabled(str(task_name or ""), False)
        return {
            "action": "pause_task",
            "origin": "auxiliary_brain",
            "status": result.get("status") or ("paused" if result.get("ok") else "failed"),
            "task_name": result.get("task_name") or task_name,
            "schedule_policy": result.get("schedule_policy"),
            "message": result.get("message") or ("Task schedule paused." if result.get("ok") else "Task schedule could not be paused."),
            "final_answer": result.get("message") or ("Task schedule paused." if result.get("ok") else "Task schedule could not be paused."),
            "error": result.get("error"),
        }

    def resume_task_schedule(self, task_name: str | None) -> dict[str, Any]:
        result = self.set_task_schedule_enabled(str(task_name or ""), True)
        return {
            "action": "resume_task",
            "origin": "auxiliary_brain",
            "status": result.get("status") or ("resumed" if result.get("ok") else "failed"),
            "task_name": result.get("task_name") or task_name,
            "schedule_policy": result.get("schedule_policy"),
            "message": result.get("message") or ("Task schedule resumed." if result.get("ok") else "Task schedule could not be resumed."),
            "final_answer": result.get("message") or ("Task schedule resumed." if result.get("ok") else "Task schedule could not be resumed."),
            "error": result.get("error"),
        }

    async def run_task_now(self, task_name: str | None, provided_inputs: dict[str, Any] | None = None, instruction: str | None = None) -> dict[str, Any]:
        inputs = dict(provided_inputs or {})
        inputs["_run_scheduled_payload_now"] = True
        inputs["_scheduled_payload_dispatch"] = True
        result = await self.execute_task(task_name, provided_inputs=inputs, instruction=instruction or "")
        result["action"] = "run_task_now"
        result["manual_payload_run"] = True
        return result

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


    def _maybe_import_python_file_capability(self, *, instruction: str, participant_name: str, artifact_refs: list[dict[str, Any]] | None) -> dict[str, Any] | None:
        """Convert an explicitly referenced Python program into a runtime capability.

        This is a generic file-to-capability bridge.  It does not know the
        program domain.  It only runs when the agent definition explicitly names
        a Python file that is present in the uploaded artifact registry.  The
        executable behavior remains in the user supplied file; the generated
        wrapper only provides the standard runtime envelope.
        """
        source = self._resolve_python_file_reference(instruction=instruction, artifact_refs=artifact_refs)
        if source is None:
            return None
        imported = self.python_file_capability_importer.import_file(
            source_path=source,
            participant_name=participant_name,
            instruction=instruction,
        )
        if not imported.get("ok"):
            return {
                "binding_status": "python_file_capability_import_failed",
                "participant_name": participant_name,
                "tool_id": "",
                "capability": "",
                "capabilities": [],
                "match_score": 0,
                "match_basis": "explicit_python_file_reference",
                "error": imported.get("error") or {"message": "Python file capability import failed."},
                "tool_summary": {},
                "parameter_contract": {
                    "contract_type": "registered_tool_parameter_contract",
                    "source": "python_file_import_failed",
                    "parameters": [],
                    "missing_information": [],
                    "runtime_scope": "task_run",
                },
                "execution_policy": {"execution_method": "runtime_registered_tool", "binding_error": imported.get("error")},
            }
        tool_id = str(imported.get("tool_id") or "").strip()
        input_schema = imported.get("input_schema") if isinstance(imported.get("input_schema"), dict) else {}
        record = imported.get("registry_record") if isinstance(imported.get("registry_record"), dict) else {}
        return {
            "binding_status": "bound_to_imported_python_file_capability",
            "participant_name": participant_name,
            "tool_id": tool_id,
            "capability": imported.get("capability") or tool_id,
            "capabilities": imported.get("capabilities") or [tool_id],
            "match_score": 100,
            "match_basis": "explicit_python_file_reference",
            "tool_summary": {
                "tool_id": tool_id,
                "name": record.get("name") or tool_id,
                "capability": record.get("capability") or tool_id,
                "capabilities": record.get("capabilities") if isinstance(record.get("capabilities"), list) else [tool_id],
                "status": record.get("status") or "enabled",
                "input_schema": input_schema,
                "connection_schema": record.get("connection_schema") if isinstance(record.get("connection_schema"), dict) else {},
                "secret_schema": record.get("secret_schema") if isinstance(record.get("secret_schema"), dict) else {},
                "approval_policy": record.get("approval_policy") if isinstance(record.get("approval_policy"), dict) else {},
            },
            "parameter_contract": self._parameter_contract_from_input_schema(tool_id=tool_id, input_schema=input_schema, source="imported_python_file_input_schema"),
            "execution_policy": {
                "execution_method": "runtime_registered_tool",
                "tool_id": tool_id,
                "source": "explicit_python_file_reference",
            },
            "imported_python_file": {
                "source_file": imported.get("source_file"),
                "artifact_dir": imported.get("artifact_dir"),
                "manifest_path": imported.get("manifest_path"),
                "callable": imported.get("callable"),
            },
        }

    def _resolve_python_file_reference(self, *, instruction: str, artifact_refs: list[dict[str, Any]] | None) -> Path | None:
        text = str(instruction or "")
        referenced_names = {m.group(1) for m in re.finditer(r"(?i)(?:file|program|code|script)\s+([A-Za-z0-9_.-]+\.py)\b", text)}
        referenced_names.update(m.group(1) for m in re.finditer(r"(?i)\b([A-Za-z0-9_.-]+\.py)\b", text))
        candidates: list[dict[str, Any]] = []
        for item in artifact_refs or []:
            if isinstance(item, dict):
                candidates.append(item)
        for item in self.artifact_registry.resolve_from_text(text):
            if isinstance(item, dict):
                candidates.append(item)
        seen: set[str] = set()
        for item in candidates:
            path_text = str(item.get("path") or "").strip()
            filename = str(item.get("filename") or item.get("name") or Path(path_text).name).strip()
            if not path_text or not filename.lower().endswith(".py"):
                continue
            if referenced_names and filename not in referenced_names and filename.lower() not in {x.lower() for x in referenced_names}:
                continue
            key = str(Path(path_text))
            if key in seen:
                continue
            seen.add(key)
            path = Path(path_text).expanduser()
            if path.exists() and path.is_file():
                return path
        # Allow explicit local paths only when they are present in the agent text.
        for raw in referenced_names:
            path = Path(raw).expanduser()
            if path.exists() and path.is_file() and path.suffix.lower() == ".py":
                return path
        return None

    def _parameter_contract_from_input_schema(self, *, tool_id: str, input_schema: dict[str, Any], source: str) -> dict[str, Any]:
        properties = input_schema.get("properties") if isinstance(input_schema.get("properties"), dict) else {}
        required = {str(x) for x in input_schema.get("required", []) if str(x).strip()} if isinstance(input_schema.get("required"), list) else set()
        params: list[dict[str, Any]] = []
        for name, prop in properties.items():
            prop = prop if isinstance(prop, dict) else {}
            schema_type = str(prop.get("type") or "string")
            params.append({
                "name": str(name),
                "label": str(prop.get("title") or name),
                "description": str(prop.get("description") or f"Provide {name}."),
                "required": str(name) in required,
                "type": "list" if schema_type == "array" else schema_type,
                "values": [],
                "collection_mode": "repeat_until_done" if schema_type == "array" else "single_value",
                "runtime_required": str(name) in required,
                "blocking": str(name) in required,
                "execution_required": str(name) in required,
                "source_schema_type": schema_type,
            })
        return {
            "contract_type": "registered_tool_parameter_contract",
            "source": source,
            "tool_id": tool_id,
            "parameters": params,
            "missing_information": [p for p in params if p.get("required")],
            "runtime_scope": "task_run",
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
        file_capability_binding = self._maybe_import_python_file_capability(
            instruction=instruction,
            participant_name=participant_name,
            artifact_refs=artifact_refs,
        )
        if file_capability_binding and not str(file_capability_binding.get("tool_id") or "").strip():
            err = file_capability_binding.get("error") if isinstance(file_capability_binding.get("error"), dict) else {"message": "Python file capability import failed."}
            return {
                "action": "create_participant",
                "origin": "auxiliary_brain",
                "status": "failed",
                "failure_class": "python_file_capability_import_failed",
                "participant_id": participant_id,
                "agent_name": participant_name,
                "final_answer": str(err.get("message") or "Python file capability import failed."),
                "error": err,
            }
        capability_binding = file_capability_binding or self.registered_tool_agent_binder.bind(
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
        explicit_runtime_parameters = self._extract_top_level_runtime_parameters_from_instruction(instruction)
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
        declared_repair = self._ensure_declared_payload_steps_preserved(
            instruction=instruction,
            tasks=workflow_plan.tasks,
            participants=participants,
            selected_participants=workflow_plan.selected_participants,
            generated_participants=workflow_plan.generated_participants,
            graph_id=graph_id,
        )
        workflow_tasks = declared_repair["tasks"]
        workflow_plan.selected_participants = declared_repair["selected_participants"]
        workflow_plan.generated_participants = declared_repair["generated_participants"]
        workflow_tasks = self._hydrate_task_step_bindings_from_participants(
            workflow_tasks,
            workflow_plan.selected_participants,
        )
        workflow_tasks = self._attach_step_source_contracts(workflow_tasks)
        explicit_runtime_parameters.update(
            self._extract_named_parameter_blocks_from_instruction(instruction, workflow_plan.selected_participants)
        )
        schedule_policy = self._materialize_schedule_policy_from_control_steps(
            schedule_policy=schedule_policy,
            tasks=workflow_tasks,
            participants=workflow_plan.selected_participants,
            runtime_parameters=explicit_runtime_parameters,
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

        normalized_graph_parts = self._normalize_scheduled_graph_after_planning(
            instruction=instruction,
            tasks=workflow_tasks,
            selected_participants=workflow_plan.selected_participants,
            generated_participants=workflow_plan.generated_participants,
            schedule_policy=schedule_policy,
            runtime_parameters=explicit_runtime_parameters,
        )
        workflow_tasks = normalized_graph_parts["tasks"]
        workflow_plan.selected_participants = normalized_graph_parts["selected_participants"]
        workflow_plan.generated_participants = normalized_graph_parts["generated_participants"]
        schedule_policy = normalized_graph_parts["schedule_policy"]
        if isinstance(schedule_policy, dict) and schedule_policy.get("enabled"):
            schedule_policy = dict(schedule_policy)
            schedule_instance_id = str(schedule_policy.get("schedule_instance_id") or f"schedule_{task_name}").strip()
            schedule_policy["schedule_instance_id"] = schedule_instance_id
            schedule_policy["lifecycle_key"] = schedule_instance_id
        selected_ids = [p.get("participant_id") for p in workflow_plan.selected_participants if p.get("participant_id")]

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

        workflow_variable_contract = self._build_workflow_variable_contract(
            tasks=workflow_tasks,
            runtime_parameters=explicit_runtime_parameters,
        )
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
            "execution_type": "scheduled" if (isinstance(schedule_policy, dict) and schedule_policy.get("enabled")) else "one_shot",
            "selected_participant_ids": selected_ids,
            "uploaded_artifacts": artifact_refs,
            "parameter_contract": schema_contract,
            "runtime_parameters": explicit_runtime_parameters,
            "workflow_variable_contract": workflow_variable_contract,
            "schedule_policy": schedule_policy,
            "schedule_instance_id": schedule_policy.get("schedule_instance_id") if isinstance(schedule_policy, dict) else None,
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
        compile_result = self.task_graph_compiler.compile_validate_save(payload)
        if compile_result.get("status") != "completed":
            validation_report = compile_result.get("validation_report") if isinstance(compile_result.get("validation_report"), dict) else {}
            self._update_community()
            return {
                "action": "create_task_graph",
                "origin": "auxiliary_brain",
                "status": "failed",
                "failure_class": "compiled_task_validation_failed",
                "graph_id": graph_id,
                "task_name": task_name,
                "message": "Task compile failed",
                "final_answer": "Task compile failed",
                "validation_report": validation_report,
            }
        payload["compiled_task"] = {
            "task_id": (compile_result.get("compiled_task") or {}).get("task_id"),
            "path": compile_result.get("compiled_task_path"),
            "validation_report": compile_result.get("validation_report"),
            "execution_mode": "execute_compiled_task",
        }
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
        return {
            "action": "create_task_graph",
            "origin": "auxiliary_brain",
            "status": "completed",
            "graph_id": graph_id,
            "task_name": task_name,
            "path": str(path),
            "uploaded_artifacts": artifact_refs,
            "schedule_policy": schedule_policy,
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
        task_step_aliases = self._task_step_aliases_for_static_validation(tasks)
        known_step_refs = declared_steps | task_step_aliases
        for template in self._extract_template_references(text):
            root = str(template.get("root") or "").strip()
            if not root:
                continue
            canonical = self._canonical_step_reference(root)
            if canonical.startswith("step_") and canonical not in known_step_refs:
                issues.append({
                    "level": "create_task_graph",
                    "check": "template_step_reference_exists",
                    "passed": False,
                    "failure_class": "template_reference_not_found",
                    "message": "A template reference points to a step that is not declared in this task instruction.",
                    "reference": template.get("raw"),
                    "root": root,
                    "canonical_root": canonical,
                    "declared_steps": sorted(declared_steps),
                    "task_step_aliases": sorted(task_step_aliases),
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
        """Return canonical step ids declared by the user instruction.

        User-authored task text may be pasted as one line or as multiple lines.
        Static validation must therefore recognize structural step headers both
        at line starts and after sentence separators, while keeping all forms in
        one canonical namespace.
        """
        ids: set[str] = set()
        for match in re.finditer(r"(?i)\bstep\s*_?\s*(\d+)\s*[:.)-]", str(text or "")):
            canonical = self._canonical_step_reference(match.group(1))
            if canonical:
                ids.add(canonical)
        return ids

    def _canonical_step_reference(self, value: Any) -> str:
        text = str(value or "").strip().casefold()
        if not text:
            return ""
        match = re.fullmatch(r"(?:step|stage)?\s*_?\s*(\d+)", text, flags=re.I)
        if match:
            return f"step_{int(match.group(1)):03d}"
        match = re.fullmatch(r"step[_-](\d+)", text, flags=re.I)
        if match:
            return f"step_{int(match.group(1)):03d}"
        return re.sub(r"[^a-z0-9_]+", "_", text).strip("_")

    def _task_step_aliases_for_static_validation(self, tasks: list[dict[str, Any]]) -> set[str]:
        aliases: set[str] = set()
        for index, task in enumerate(tasks or [], start=1):
            if not isinstance(task, dict):
                continue
            for value in (
                index,
                task.get("source_step_id"),
                task.get("step_id"),
                task.get("task_id"),
                task.get("participant_id"),
            ):
                canonical = self._canonical_step_reference(value)
                if canonical:
                    aliases.add(canonical)
        return aliases

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


    def _load_authoritative_task_graph_for_execution(self, task_name: str) -> tuple[dict[str, Any] | None, bool]:
        """Load the executable task graph with compiled artifacts as authority.

        Saved task json files are creation-time records and may still contain
        legacy participant selections.  When a compiled task directory exists
        and passed validation, execution must use that compiled graph first so
        bindings are resolved from compiled steps instead of the old delegation
        graph.  This rule is generic and independent of capability names.
        """
        name = str(task_name or "").strip()
        if not name:
            return None, False
        compiled = self.compiled_task_loader.as_task_graph(name)
        if compiled:
            compiled["_execution_authority"] = "compiled_task"
            return compiled, True
        legacy = self.store.read_json(f"generated/tasks/{name}.json")
        return (legacy if isinstance(legacy, dict) else None), False

    def _execution_participants_for_task_graph(self, task_graph: dict[str, Any]) -> list[dict[str, Any]]:
        """Return participants for the current executable graph only.

        Compiled task graphs can contain generated semantic steps that are not
        durable agents.  They must be rebuilt from the task graph and included
        before registered tool steps.  Do not fall back to all durable agents
        when selected ids are declared, because that reintroduces the legacy
        delegation path and can skip upstream compiled steps.
        """
        all_participants = self.store.list_json("generated/agents")
        selected_ids = {str(x).strip() for x in (task_graph.get("selected_participant_ids") or []) if str(x).strip()}
        if not selected_ids:
            return all_participants
        participants = [p for p in all_participants if str(p.get("participant_id") or p.get("id") or "").strip() in selected_ids]
        found_ids = {str(p.get("participant_id") or p.get("id") or "").strip() for p in participants}
        missing_ids = selected_ids - found_ids
        if missing_ids:
            participants.extend(self._participants_from_task_graph(task_graph, missing_ids))
        order = {pid: i for i, pid in enumerate(task_graph.get("selected_participant_ids") or [])}
        participants.sort(key=lambda p: order.get(str(p.get("participant_id") or p.get("id") or "").strip(), 10**9))
        return participants

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
        resolved_task_name = self._resolve_task_name(task_name) or str(task_name or "").strip()
        task_graph, compiled_loaded = self._load_authoritative_task_graph_for_execution(resolved_task_name)
        if isinstance(task_graph, dict):
            task_graph = self.execution_reuse_policy_classifier.apply_to_task_graph(task_graph)
        if not task_graph:
            return {
                "action": "execute_task_graph",
                "origin": "auxiliary_brain",
                "status": "not_found",
                "task_name": task_name,
            }
        task_name = resolved_task_name
        if not compiled_loaded:
            compile_result = self.task_graph_compiler.compile_validate_save(task_graph)
            if compile_result.get("status") != "completed":
                return {
                    "action": "execute_task_graph",
                    "origin": "auxiliary_brain",
                    "status": "blocked",
                    "task_name": task_name,
                    "message": "Task compile failed",
                    "final_answer": "Task compile failed",
                    "validation_report": compile_result.get("validation_report"),
                }
            task_graph, compiled_loaded = self._load_authoritative_task_graph_for_execution(resolved_task_name)
            if isinstance(task_graph, dict):
                task_graph = self.execution_reuse_policy_classifier.apply_to_task_graph(task_graph)
            if not task_graph:
                task_graph = self.store.read_json(f"generated/tasks/{task_name}.json") or {}
        execution_type = self._task_execution_type(task_graph)
        schedule_policy = self._task_schedule_policy(task_graph)
        runtime_state_manager.emit(run_id=state_run_id, step_id="task.load", level="developer", kind="validation", status="completed", title="Task graph loaded", message="Task graph loaded from runtime storage.", output={"task_name": task_name, "task_count": len(task_graph.get("tasks") or []) if isinstance(task_graph, dict) else 0, "execution_type": execution_type, "schedule_state": schedule_policy.get("state")}, progress=100)
        if self._task_instruction_changed(task_graph):
            runtime_state_manager.emit(run_id=state_run_id, step_id="task.rebuild", level="developer", kind="repair", status="running", title="Task graph rebuild", message="Instruction changed; rebuilding the task graph from current instruction.", method="instruction_workflow_planner", progress=20)
            task_graph = self._rebuild_task_graph_from_current_instruction(task_graph)
            execution_type = self._task_execution_type(task_graph)
            schedule_policy = self._task_schedule_policy(task_graph)
            runtime_state_manager.emit(run_id=state_run_id, step_id="task.rebuild", level="developer", kind="repair", status="completed", title="Task graph rebuilt", message="Task graph rebuild completed.", output={"execution_type": execution_type, "schedule_state": schedule_policy.get("state")}, progress=100)
        provided_inputs = provided_inputs or {}
        activation_response = self._maybe_activate_durable_schedule_on_manual_execution(
            task_name=task_name,
            task_graph=task_graph,
            provided_inputs=provided_inputs,
        )
        if activation_response is not None:
            runtime_state_manager.emit(
                run_id=state_run_id,
                step_id="execution.schedule",
                level="user",
                kind="lifecycle",
                status="completed",
                title="Schedule activated",
                message="The task schedule was activated; payload execution will be dispatched by the runtime scheduler.",
                output={"task_name": task_name, "schedule_policy": activation_response.get("schedule_policy")},
                progress=100,
            )
            return activation_response
        payload_only_ids = self._execution_payload_only_ids(task_graph, provided_inputs)
        payload_only_execution = bool(payload_only_ids)
        if payload_only_ids:
            task_graph = self._task_graph_with_payload_only_participants(task_graph, payload_only_ids)
        participants = self._execution_participants_for_task_graph(task_graph)
        runtime_parameters = {}
        if isinstance(task_graph.get("runtime_parameters"), dict):
            runtime_parameters.update(task_graph.get("runtime_parameters") or {})
        runtime_parameters.update(self._extract_step_scoped_runtime_parameters_from_tasks(task_graph.get("tasks") if isinstance(task_graph.get("tasks"), list) else []))
        runtime_parameters.update(self._extract_named_parameter_blocks_from_instruction(str(task_graph.get("instruction") or ""), participants))
        runtime_parameters.update(self._extract_top_level_runtime_parameters_from_instruction(instruction or ""))
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
            if self._task_graph_allows_execution_reuse(task_graph, participants):
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
            "execution_type": execution_type,
            "schedule_policy": schedule_policy if execution_type == "scheduled" else {"enabled": False, "mode": "none", "state": "none"},
            "schedule_state": str((schedule_policy or {}).get("state") or "none") if execution_type == "scheduled" else "none",
            "final_answer": self._compact_final_answer((result.get("synthesis") or {}).get("final_answer")),
            "delivery": result.get("delivery"),
        }
        if status in {"requires_key", "requires_input", "paused"}:
            pending_action = result.get("pending_action")
            response["pending_action"] = pending_action
            response["missing_inputs"] = self._normalize_missing_inputs(result.get("missing_inputs", []), pending_action)
            pause_reason = self._execution_pause_reason(response["missing_inputs"], pending_action)
            response["pause_reason"] = pause_reason
            response["interaction_request"] = {
                "type": "collect_runtime_parameters",
                "kind": str((pending_action or {}).get("kind") or "runtime_parameter_input"),
                "fields": response["missing_inputs"],
                "message": self._paused_message(response["missing_inputs"], pending_action),
                "pause_reason": pause_reason,
                "execution_type": execution_type,
                "schedule_state": response.get("schedule_state"),
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
            if self._should_use_lightweight_result_verification(task_graph, provided_inputs):
                response["verification"] = {
                    "status": "completed",
                    "method": "lightweight_structural",
                    "reason": "compiled_direct_scheduled_dispatch",
                    "replanned": False,
                }
                runtime_state_manager.emit(run_id=state_run_id, step_id="result.verify", level="developer", kind="verification", status="completed", title="Result verification completed", message="lightweight_structural", output={"verification": response.get("verification")}, progress=100)
            else:
                runtime_state_manager.emit(run_id=state_run_id, step_id="result.verify", level="user", kind="verification", status="running", title="Result verification", message="Verifying execution material and response quality.", method="verification_brain", progress=40)
                self._attach_verification_report(task_graph=task_graph, participants=participants, run_payload=result, response=response, stage="execute_task")
                runtime_state_manager.emit(run_id=state_run_id, step_id="result.verify", level="developer", kind="verification", status="completed", title="Result verification completed", message=str((response.get("verification") or {}).get("status") or "completed"), output={"verification": response.get("verification")}, progress=100)
        runtime_state_manager.emit(run_id=state_run_id, step_id="final.synthesis", level="user", kind="output", status=status, title="Final synthesis", message="Final response prepared for the user.", output={"status": status, "has_final_answer": bool(response.get("final_answer"))}, progress=100)
        return response

    def _should_use_lightweight_result_verification(self, task_graph: dict[str, Any], provided_inputs: dict[str, Any] | None) -> bool:
        if not isinstance(task_graph, dict):
            return False
        provided_inputs = provided_inputs or {}
        if not bool(provided_inputs.get("_scheduled_payload_dispatch") or provided_inputs.get("_run_scheduled_payload_now")):
            return False
        policy = task_graph.get("execution_reuse_policy") if isinstance(task_graph.get("execution_reuse_policy"), dict) else {}
        return str(policy.get("mode") or "").strip().casefold() == COMPILED_DIRECT

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
        resolved_task_name = self._resolve_task_name(task_name) or task_name
        task_graph, _compiled_loaded = self._load_authoritative_task_graph_for_execution(resolved_task_name)
        if not task_graph:
            return {
                "action": "resume_task_graph",
                "origin": "auxiliary_brain",
                "status": "not_found",
                "run_id": run_id,
                "task_name": task_name,
            }
        task_name = resolved_task_name
        participants = self._execution_participants_for_task_graph(task_graph)
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
        dispatch_requested = bool(provided_inputs.get("_scheduled_payload_dispatch") or provided_inputs.get("_run_scheduled_payload_now"))
        if not schedule_enabled and not dispatch_requested:
            return []
        controllers = {str(x).strip() for x in (policy.get("controller_participant_ids") or []) if str(x).strip()}
        tasks = task_graph.get("tasks") if isinstance(task_graph.get("tasks"), list) else []
        derived: list[str] = []
        for item in tasks:
            if not isinstance(item, dict):
                continue
            pid = str(item.get("participant_id") or "").strip()
            if pid and pid not in controllers and pid not in derived:
                derived.append(pid)
        if derived:
            return derived
        if not controllers:
            return []
        selected = [str(x).strip() for x in (task_graph.get("selected_participant_ids") or []) if str(x).strip()]
        return [x for x in selected if x and x not in controllers]

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
        reason = self._execution_pause_reason(missing_inputs or [], pending)
        if reason == "runtime_approval_required":
            return "One-shot task execution is waiting for runtime approval. This is not a schedule pause."
        if reason == "runtime_input_required":
            return "One-shot task execution is waiting for required runtime input. This is not a schedule pause."
        if kind == "validation_recovery":
            return "One-shot task execution paused after schema validation failed. Runtime auto repair should handle structural errors before asking the user."
        return "One-shot task execution is paused for runtime interaction. This is not a schedule pause."




    def _step_source_contract_from_fragment(self, fragment: Any) -> dict[str, Any]:
        """Build a structural source-material contract from a step fragment.

        The contract is topic-neutral.  It does not split one instruction into
        multiple work units just because the instruction contains a requested
        count.  A requested count is stored as output cardinality metadata for
        the same step.
        """
        text = str(fragment or "")
        requested_fields: list[str] = []
        for raw in text.splitlines():
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
        output_cardinality = self._structural_output_cardinality(text)
        return {
            "contract_type": "step_source_material_contract",
            "requires_source_material": requires_source_material,
            "requested_output_fields": requested_fields,
            "output_cardinality": output_cardinality,
            "single_step_multi_item_output": bool(output_cardinality.get("requested_count")),
            "reason": "requested_output_provenance_fields" if requires_source_material else "not_declared",
        }

    def _structural_output_cardinality(self, text: str) -> dict[str, Any]:
        """Extract generic item-count requirements without topic vocabulary.

        This is intentionally syntax-only.  It recognizes numerals and simple
        English number words near generic collection nouns, and preserves that
        as output metadata.  It never creates extra workflow steps.
        """
        raw = str(text or "")
        lower = raw.casefold()
        word_numbers = {
            "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        }
        patterns = [
            r"(?<![A-Za-z0-9_])(?P<n>\d{1,2})\s+(?:of\s+the\s+)?(?:latest|recent|newest|top|first|last)?\s*[^\n.。:：]{0,80}(?:\n|$|[.。:：])",
            r"(?<![A-Za-z0-9_])(?P<n>one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:of\s+the\s+)?(?:latest|recent|newest|top|first|last)?\s*[^\n.。:：]{0,80}(?:\n|$|[.。:：])",
        ]
        requested_count = 0
        matched = ""
        for pattern in patterns:
            match = re.search(pattern, lower, flags=re.I)
            if not match:
                continue
            token = str(match.group("n") or "").casefold()
            requested_count = int(token) if token.isdigit() else int(word_numbers.get(token, 0) or 0)
            matched = match.group(0)
            break
        if requested_count <= 0:
            return {"mode": "unspecified"}
        return {
            "mode": "exact_requested_count",
            "requested_count": requested_count,
            "source": "structural_instruction",
            "matched_text": matched,
            "compile_policy": "preserve_as_single_step_output_requirement",
        }

    def _attach_step_source_contracts(self, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for task in tasks or []:
            if not isinstance(task, dict):
                continue
            task["source_contract"] = self._step_source_contract_from_fragment(task.get("source_instruction_fragment") or task.get("objective") or task.get("instruction"))
        return tasks

    def _controller_participant_ids_from_runtime_parameters(self, runtime_parameters: dict[str, Any]) -> set[str]:
        controllers: set[str] = set()
        if not isinstance(runtime_parameters, dict):
            return controllers
        for key, value in runtime_parameters.items():
            key_text = str(key or "").strip()
            if not key_text:
                continue
            prefix = key_text.rsplit(".", 1)[0] if "." in key_text else ""
            field = key_text.rsplit(".", 1)[-1]
            if prefix and self._is_timing_parameter_key(field):
                controllers.add(prefix)
            if isinstance(value, dict):
                nested_keys = {str(k or "").strip() for k in value.keys()}
                if any(self._is_timing_parameter_key(k) for k in nested_keys):
                    controllers.add(key_text)
        return controllers

    def _build_workflow_variable_contract(self, *, tasks: list[dict[str, Any]], runtime_parameters: dict[str, Any]) -> dict[str, Any]:
        """Create an explicit dataflow binding contract for the task graph.

        The task creator converts user-authored ``{{step.field}}`` references
        into structural binding metadata before execution.  The original string
        is preserved for compatibility, but graph/runtime viewers and executors
        can inspect this contract instead of guessing at execution time.  This is
        syntax-only and domain-neutral.
        """
        import re
        template_re = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
        controller_ids = self._controller_participant_ids_from_runtime_parameters(runtime_parameters)
        payload_tasks = [t for t in (tasks or []) if isinstance(t, dict) and str(t.get("participant_id") or "").strip() not in controller_ids]
        step_aliases: dict[str, str] = {}
        for index, task in enumerate(payload_tasks, start=1):
            if not isinstance(task, dict):
                continue
            canonical_step_id = str(task.get("source_step_id") or task.get("step_id") or "").strip() or f"step_{index:03d}"
            pid = str(task.get("participant_id") or "").strip()
            aliases = {
                f"step{index}", f"step_{index}", f"step {index}", f"step_{index:03d}",
                f"stage{index}", f"stage_{index}", f"stage {index}", f"stage_{index:03d}",
                str(task.get("source_step_id") or "").strip(),
                str(task.get("step_id") or "").strip(),
                str(task.get("task_id") or "").strip(),
                canonical_step_id,
            }
            if pid:
                aliases.add(pid)
            for alias in aliases:
                norm = self._normalize_workflow_reference(alias)
                if norm:
                    step_aliases[norm] = canonical_step_id
                canonical_norm = self._normalize_workflow_reference(self._canonical_step_reference(alias))
                if canonical_norm:
                    step_aliases[canonical_norm] = canonical_step_id
        bindings: list[dict[str, Any]] = []
        for key, value in (runtime_parameters or {}).items():
            if not isinstance(value, str) or "{{" not in value:
                continue
            for match in template_re.finditer(value):
                ref = match.group(1).strip()
                source_ref, _, field = ref.partition(".")
                source_step_id = step_aliases.get(self._normalize_workflow_reference(source_ref))
                source_step_id = source_step_id or step_aliases.get(self._normalize_workflow_reference(self._canonical_step_reference(source_ref)))
                source_field = field or "final_answer"
                if source_field == "final_answer":
                    source_field = "presentation.final_answer"
                bindings.append({
                    "target_path": str(key),
                    "reference": ref,
                    "source_step_id": source_step_id or "",
                    "source_step": source_step_id or "",
                    "source_alias": source_ref,
                    "source_field": source_field,
                    "binding_type": "workflow_output",
                    "status": "pending",
                })
        for task in payload_tasks:
            if not isinstance(task, dict):
                continue
            task_bindings = []
            target_aliases = self._workflow_binding_target_aliases(task)
            for item in bindings:
                target = str(item.get("target_path") or "")
                target_root = re.split(r"[._]", target, maxsplit=1)[0] if target else ""
                normalized_target_root = self._normalize_workflow_reference(target_root)
                normalized_target_full = self._normalize_workflow_reference(target)
                if normalized_target_root in target_aliases or any(normalized_target_full.startswith(alias) for alias in target_aliases):
                    task_bindings.append(item)
            if task_bindings:
                task["workflow_bindings"] = task_bindings
        return {
            "contract_type": "workflow_variable_contract",
            "binding_count": len(bindings),
            "bindings": bindings,
        }

    def _workflow_binding_target_aliases(self, task: dict[str, Any]) -> set[str]:
        aliases: set[str] = set()
        for value in (
            task.get("participant_id"),
            task.get("participant"),
            task.get("agent_id"),
            task.get("participant_display_name"),
            task.get("display_name"),
            task.get("name"),
            task.get("source_step_id"),
            task.get("step_id"),
            task.get("task_id"),
        ):
            norm = self._normalize_workflow_reference(value)
            if norm:
                aliases.add(norm)
        return aliases

    def _normalize_workflow_reference(self, value: Any) -> str:
        text = str(value or "").strip().casefold()
        text = re.sub(r"\s+", "", text)
        text = text.replace("-", "_")
        text = re.sub(r"_+", "_", text)
        return text.strip("_")

    def _extract_top_level_runtime_parameters_from_instruction(self, instruction: str) -> dict[str, Any]:
        """Extract only task-level runtime parameters.

        A composite workflow may contain scoped parameter blocks inside numbered
        steps. Those values belong to the step/participant that owns the block,
        not to every step in the run.  This method removes explicit step
        fragments before using the generic assignment parser, so downstream
        parameters cannot pollute an upstream step that is sent back to ai_core
        as an independent request.
        """
        text = str(instruction or "")
        if not text.strip():
            return {}
        redacted = self._remove_numbered_step_bodies(text)
        return self._extract_runtime_parameters_from_instruction(redacted)

    def _remove_numbered_step_bodies(self, instruction: str) -> str:
        """Keep preamble text and remove explicit numbered step bodies.

        This is syntax-only decomposition.  It intentionally knows nothing
        about business domains or capability names; it only recognizes generic
        numbered step labels.
        """
        text = str(instruction or "")
        pattern = re.compile(r"(?is)(?<![\w{])(?:^|[\r\n]+|[.;。]|\s{2,}|\s+)(?:step\s*\d+|\d+)\s*[:：.)-]\s*")
        match = pattern.search(text)
        if not match:
            return text
        return text[: match.start()].strip()

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
        # Do not write unscoped fallbacks for values discovered inside step
        # fragments.  In a composite workflow those values are scoped to the
        # step/participant that owns the fragment.  A global fallback would be
        # injected into unrelated upstream steps when they are executed through
        # ai_core and can corrupt intent recognition/planning.
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
            # Values extracted from an addressed parameter block remain scoped
            # to that participant.  Do not create plain fallback keys here: in a
            # composite workflow, unscoped runtime inputs can be injected into
            # unrelated upstream steps and change their ai_core planning.


    def _field_participant_id(self, field: dict[str, Any]) -> str:
        if not isinstance(field, dict):
            return ""
        explicit = str(field.get("participant_id") or "").strip()
        if explicit:
            return explicit
        raw = str(field.get("field") or field.get("name") or "").strip()
        if "." in raw:
            return raw.split(".", 1)[0].strip()
        return ""

    def _find_participant_by_id(self, participants: list[dict[str, Any]], participant_id: str) -> dict[str, Any] | None:
        wanted = str(participant_id or "").strip()
        if not wanted:
            return None
        for participant in participants or []:
            if not isinstance(participant, dict):
                continue
            aliases = {
                str(participant.get("participant_id") or "").strip(),
                str(participant.get("id") or "").strip(),
            }
            if wanted in aliases:
                return participant
        return None

    def _participant_display_aliases(self, participant: dict[str, Any]) -> list[str]:
        aliases: list[str] = []
        for key in ("participant_id", "id", "name", "agent_name", "display_name", "role_name"):
            value = str(participant.get(key) or "").strip() if isinstance(participant, dict) else ""
            if value and value not in aliases:
                aliases.append(value)
            underscored = value.replace(" ", "_") if value else ""
            if underscored and underscored not in aliases:
                aliases.append(underscored)
        return aliases

    def _approval_field_is_auto_confirmed(self, *, field: dict[str, Any], participants: list[dict[str, Any]], runtime_parameters: dict[str, Any]) -> bool:
        """Return True when a discovered approval field is already covered by policy.

        Approval is an execution-control concern, not a business parameter.  The
        Studio preflight layer used to surface approval_confirmed as missing
        before the registered-tool executor could read its persisted approval
        policy.  This bridge lets preflight consult the same policy store used by
        execution and injects the legacy flag only when the policy allows it.
        """
        try:
            if not self.delegation_runtime._is_approval_parameter_field(field):
                return False
        except Exception:
            return False
        participant = self._find_participant_by_id(participants, self._field_participant_id(field))
        if not participant:
            return False
        try:
            tool_id = self.delegation_runtime._participant_tool_id(participant)
        except Exception:
            tool_id = ""
        if not tool_id:
            return False
        profile_id = str((participant.get("runtime_parameters") or {}).get("profile_id") or runtime_parameters.get("profile_id") or "default")
        try:
            trusted = self.delegation_runtime._approval_trusted(participant=participant, tool_id=tool_id, profile_id=profile_id)
        except Exception:
            trusted = False
        if not trusted:
            return False
        # Do not inject approval_confirmed into runtime parameters.
        # This method is only a preflight filter: when the persisted tool policy
        # is auto-approved, the approval field should disappear from the missing
        # input form, while the executor later passes the approval state as
        # execution metadata rather than as tool input.
        return True

    def _filter_auto_confirmed_approval_fields(self, *, fields: list[dict[str, Any]], participants: list[dict[str, Any]], runtime_parameters: dict[str, Any]) -> list[dict[str, Any]]:
        filtered: list[dict[str, Any]] = []
        for field in fields or []:
            if not isinstance(field, dict):
                continue
            if self._approval_field_is_auto_confirmed(field=field, participants=participants, runtime_parameters=runtime_parameters):
                continue
            filtered.append(field)
        return filtered

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


    def _filter_deferred_execution_control_fields(self, fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Defer execution-control prompts until their graph node is reached.

        Pre-execution parameter collection must not pause the whole task graph
        for a downstream side-effect approval.  If it does, upstream producer
        steps never run and explicit dataflow placeholders such as
        ``{{Step1.final_answer}}`` cannot be resolved.  This filter is generic:
        it only recognizes execution-control fields through the existing
        delegation runtime approval-control classifier, not through capability
        names or business terms.
        """
        out: list[dict[str, Any]] = []
        for field in fields or []:
            if not isinstance(field, dict):
                continue
            try:
                if self.delegation_runtime._is_approval_parameter_field(field):
                    continue
            except Exception:
                pass
            out.append(field)
        return out

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
        agent_fields = self._filter_auto_confirmed_approval_fields(
            fields=agent_fields,
            participants=selected,
            runtime_parameters=runtime_parameters,
        )
        agent_fields = self._filter_deferred_execution_control_fields(agent_fields)

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

    def _ensure_declared_payload_steps_preserved(
        self,
        *,
        instruction: str,
        tasks: list[dict[str, Any]],
        participants: list[dict[str, Any]],
        selected_participants: list[dict[str, Any]],
        generated_participants: list[dict[str, Any]],
        graph_id: str,
    ) -> dict[str, Any]:
        """Preserve all user-declared executable payload steps after planning.

        Semantic planning may focus on explicit participant calls and omit a
        numbered natural-language step.  The compiler must not renumber the
        remaining step and bind Step1 to the wrong node.  This pass uses only
        structural step markers and declared participant references; it does not
        encode domain words, providers, counts, or concrete business actions.
        """
        structural_steps = StructuralStepPlanner().build_steps(str(instruction or ""), participants or [])
        if not structural_steps:
            return {
                "tasks": [dict(t) for t in tasks or [] if isinstance(t, dict)],
                "selected_participants": [dict(p) for p in selected_participants or [] if isinstance(p, dict)],
                "generated_participants": [dict(p) for p in generated_participants or [] if isinstance(p, dict)],
            }

        selected = [dict(p) for p in selected_participants or [] if isinstance(p, dict)]
        generated = [dict(p) for p in generated_participants or [] if isinstance(p, dict)]
        existing = [dict(t) for t in tasks or [] if isinstance(t, dict)]
        existing_by_declared: dict[str, dict[str, Any]] = {}
        for task in existing:
            key = self._canonical_step_reference(task.get("source_step_id") or task.get("step_id") or task.get("id"))
            if key and key not in existing_by_declared:
                existing_by_declared[key] = task

        ordered: list[dict[str, Any]] = []
        used_task_ids: set[int] = set()
        generated_by_source: dict[str, dict[str, Any]] = {}
        for participant in generated:
            source_key = self._canonical_step_reference(participant.get("source_step_id"))
            if source_key:
                generated_by_source[source_key] = participant

        for structural in structural_steps:
            source_key = self._canonical_step_reference(structural.get("declared_step_id") or structural.get("id"))
            if not source_key:
                continue
            # Declared executable steps are the source of truth.  A semantic
            # planner may assign a different participant to the same ordinal or
            # drop a non-agent payload step.  Re-synthesizing from the declared
            # structural step prevents Step1 from being remapped to the only
            # remaining participant step after control-plane normalization.
            synthesized = self._task_from_structural_step(
                structural,
                participants=participants,
                selected_participants=selected,
                generated_participants=generated,
                generated_by_source=generated_by_source,
                graph_id=graph_id,
                ordinal=len(ordered) + 1,
            )
            if synthesized:
                ordered.append(synthesized)

        # When the user declares an ordered step list, the declared list is the
        # complete payload graph.  Extra semantic-planner tasks are discarded
        # because they may be controller echoes or duplicate participant steps
        # with shifted ordinals.  This keeps StepN aliases bound to the user's
        # declared payload steps, not to planner side effects.

        return {
            "tasks": ordered,
            "selected_participants": self._dedupe_selected_participants(selected),
            "generated_participants": self._dedupe_selected_participants(generated),
        }

    def _task_from_structural_step(
        self,
        structural: dict[str, Any],
        *,
        participants: list[dict[str, Any]],
        selected_participants: list[dict[str, Any]],
        generated_participants: list[dict[str, Any]],
        generated_by_source: dict[str, dict[str, Any]],
        graph_id: str,
        ordinal: int,
    ) -> dict[str, Any]:
        source_step_id = str(structural.get("declared_step_id") or structural.get("id") or f"structural_step_{ordinal}").strip()
        route = structural.get("route") if isinstance(structural.get("route"), dict) else {}
        route_ref = str(route.get("participant_id") or route.get("participant_name") or structural.get("participant_id") or "").strip()
        participant = self.instruction_workflow_planner._find_participant(route_ref, participants or []) if route_ref else None
        depends_on = [self._dependency_ref_value(x) for x in (structural.get("depends_on") or [])]
        depends_on = [x for x in depends_on if x]
        if participant:
            pid = self.instruction_workflow_planner._participant_id(participant)
            if pid and not any(str(p.get("participant_id") or p.get("id") or "") == pid for p in selected_participants):
                selected_participants.append(participant)
            return {
                "id": str(structural.get("id") or source_step_id),
                "declared_step_id": source_step_id,
                "task_id": f"{graph_id}_delegate_{ordinal}",
                "participant_id": pid,
                "participant_display_name": self.instruction_workflow_planner._participant_name(participant),
                "execution_owner": "ai_core",
                "status": "pending",
                "step_type": "participant_execution",
                "depends_on": depends_on,
                "input_from": depends_on,
                "source_step_id": source_step_id,
                "source_instruction_fragment": structural.get("instruction_fragment") or "",
                "parameter_contract": self.instruction_workflow_planner._generated_parameter_contract_from_step(structural),
                "capability_profile": (
                    structural.get("capability_profile")
                    if isinstance(structural.get("capability_profile"), dict) and structural.get("capability_profile")
                    else (participant.get("capability_profile") if isinstance(participant.get("capability_profile"), dict) else {})
                ),
                **self.instruction_workflow_planner._task_contracts_from_step(structural, depends_on),
            }

        source_key = self._canonical_step_reference(source_step_id)
        virtual = generated_by_source.get(source_key)
        if not virtual:
            virtual_id = new_id("participant")
            objective = self.instruction_workflow_planner._objective_from_step(structural)
            parameter_contract = self.instruction_workflow_planner._generated_parameter_contract_from_step(structural)
            capability_profile = structural.get("capability_profile") if isinstance(structural.get("capability_profile"), dict) else {}
            virtual = {
                "participant_id": virtual_id,
                "name": structural.get("label") or f"Generated Step {ordinal}",
                "agent_name": structural.get("label") or f"Generated Step {ordinal}",
                "display_name": structural.get("label") or f"Generated Step {ordinal}",
                "role_name": structural.get("label") or f"Generated Step {ordinal}",
                "instruction": objective,
                "execution_objective": objective,
                "definition_instruction": structural.get("instruction_fragment") or objective,
                "parameter_contract": parameter_contract,
                "capability_profile": capability_profile,
                "runtime_parameters": {},
                "missing_information": [],
                "origin": "auxiliary_brain",
                "status": "created",
                "execution_policy": "delegate_to_ai_core",
                "generated_by": "structural_workflow_repair",
                "depends_on": depends_on,
                "input_from": depends_on,
                "workflow_step_type": "semantic_intermediate_step",
                "source_step_id": source_step_id,
                "declared_step_id": source_step_id,
                "structural_step_id": str(structural.get("id") or ""),
            }
            generated_participants.append(virtual)
            generated_by_source[source_key] = virtual
        return {
            "id": str(structural.get("id") or source_step_id),
            "declared_step_id": source_step_id,
            "task_id": f"{graph_id}_delegate_{ordinal}",
            "participant_id": str(virtual.get("participant_id") or ""),
            "participant_display_name": str(virtual.get("display_name") or virtual.get("name") or "Runtime Step"),
            "execution_owner": "ai_core",
            "status": "pending",
            "step_type": "semantic_intermediate_step",
            "depends_on": depends_on,
            "input_from": depends_on,
            "source_step_id": source_step_id,
            "source_instruction_fragment": structural.get("instruction_fragment") or "",
            "parameter_contract": virtual.get("parameter_contract") if isinstance(virtual.get("parameter_contract"), dict) else {},
            "capability_profile": virtual.get("capability_profile") if isinstance(virtual.get("capability_profile"), dict) else {},
            **self.instruction_workflow_planner._task_contracts_from_step(structural, depends_on),
        }

    def _participant_reuse_key(self, participant: dict[str, Any]) -> str:
        name = str(participant.get("name") or participant.get("agent_name") or participant.get("display_name") or "").strip().casefold()
        objective = str(participant.get("execution_objective") or participant.get("instruction") or "").strip().casefold()
        objective = re.sub(r"\s+", " ", objective)[:180]
        artifacts = participant.get("uploaded_artifacts") if isinstance(participant.get("uploaded_artifacts"), list) else []
        artifact_sig = ",".join(sorted(str(a.get("artifact_id") or a.get("path") or a.get("filename") or "") for a in artifacts if isinstance(a, dict)))
        return "|".join(part for part in (name, objective, artifact_sig) if part)



    def _normalize_scheduled_graph_after_planning(
        self,
        *,
        instruction: str,
        tasks: list[dict[str, Any]],
        selected_participants: list[dict[str, Any]],
        generated_participants: list[dict[str, Any]],
        schedule_policy: dict[str, Any],
        runtime_parameters: dict[str, Any],
    ) -> dict[str, Any]:
        """Normalize a planned graph before validation and compilation.

        A timing controller is task-level metadata, not payload work.  Runtime
        semantic planning can still return such controller fragments as ordinary
        steps.  This post-planning pass removes those control-plane steps,
        flattens dependency records, and reassigns payload-local step aliases so
        user references such as Step 1 always point to the first executable
        payload step.
        """
        tasks = [dict(t) for t in (tasks or []) if isinstance(t, dict)]
        selected_participants = [dict(p) for p in (selected_participants or []) if isinstance(p, dict)]
        generated_participants = [dict(p) for p in (generated_participants or []) if isinstance(p, dict)]
        policy = dict(schedule_policy or {})

        controller_ids = set(str(x).strip() for x in (policy.get("controller_participant_ids") or []) if str(x).strip())
        controller_ids.update(self._controller_ids_from_instruction_preamble(instruction, selected_participants + generated_participants))
        controller_ids.update(self._controller_ids_from_task_timing(tasks, selected_participants + generated_participants, runtime_parameters))

        if controller_ids:
            policy["controller_participant_ids"] = sorted(controller_ids)
            policy.setdefault("enabled", True)
            if not str(policy.get("mode") or "").strip() or str(policy.get("mode") or "").strip() == "none":
                policy["mode"] = "recurring"

        id_aliases: dict[str, str] = {}
        payload: list[dict[str, Any]] = []
        removed_ids: set[str] = set(controller_ids)
        for raw in tasks:
            pid = str(raw.get("participant_id") or raw.get("participant") or raw.get("agent_id") or "").strip()
            source_step_id = str(raw.get("source_step_id") or raw.get("step_id") or raw.get("id") or "").strip()
            if pid in controller_ids or self._task_declares_timing_control(raw):
                if pid:
                    removed_ids.add(pid)
                if source_step_id:
                    removed_ids.add(source_step_id)
                continue
            payload.append(dict(raw))

        for index, task in enumerate(payload, start=1):
            canonical = f"step_{index:03d}"
            old_values = [
                task.get("source_step_id"), task.get("step_id"), task.get("id"),
                task.get("participant_id"), task.get("participant"), task.get("agent_id"),
                index, f"Step{index}", f"Step {index}", f"step_{index}", canonical,
            ]
            for value in old_values:
                text = str(value or "").strip()
                if text:
                    id_aliases[text] = canonical
                    id_aliases[self._normalize_workflow_reference(text)] = canonical
                    id_aliases[self._canonical_step_reference(text)] = canonical
            task["source_step_id"] = canonical
            task["step_id"] = canonical

        for task in payload:
            task["depends_on"] = self._normalize_dependency_list_for_task(task.get("depends_on"), id_aliases, removed_ids)
            task["input_from"] = self._normalize_dependency_list_for_task(task.get("input_from") or task.get("depends_on"), id_aliases, removed_ids)
            task["workflow_bindings"] = self._normalize_task_workflow_bindings(task.get("workflow_bindings"), id_aliases, removed_ids)

        selected_participants = [p for p in selected_participants if str(p.get("participant_id") or p.get("id") or "").strip() not in controller_ids]
        generated_participants = [p for p in generated_participants if str(p.get("participant_id") or p.get("id") or "").strip() not in controller_ids]
        return {
            "tasks": payload,
            "selected_participants": selected_participants,
            "generated_participants": generated_participants,
            "schedule_policy": policy,
        }

    def _controller_ids_from_instruction_preamble(self, instruction: str, participants: list[dict[str, Any]]) -> set[str]:
        text = str(instruction or "")
        first_step = re.search(r"(?i)\bstep\s*_?\s*\d+\s*[:.)-]", text)
        preamble = text[: first_step.start()] if first_step else text
        if not self._extract_generic_interval_seconds(preamble) and not any(self._is_timing_parameter_key(k) for k in self._extract_runtime_parameters_from_instruction(preamble).keys()):
            return set()
        refs = self._extract_declared_participant_references(preamble)
        if not refs:
            return set()
        name_index = self._static_participant_name_index(participants)
        out: set[str] = set()
        for ref in refs:
            norm = self._static_normalize_name(ref.get("name"))
            participant = name_index.get(norm)
            if isinstance(participant, dict):
                pid = str(participant.get("participant_id") or participant.get("id") or "").strip()
                if pid:
                    out.add(pid)
        return out

    def _controller_ids_from_task_timing(self, tasks: list[dict[str, Any]], participants: list[dict[str, Any]], runtime_parameters: dict[str, Any]) -> set[str]:
        derived = self._derive_execution_controller_participant_ids(tasks=tasks, participants=participants, runtime_parameters=runtime_parameters)
        return {str(x).strip() for x in derived if str(x).strip()}

    def _task_declares_timing_control(self, task: dict[str, Any]) -> bool:
        fragment = "\n".join(str(task.get(k) or "") for k in ("source_instruction_fragment", "instruction", "objective", "execution_objective"))
        values = self._extract_runtime_parameters_from_instruction(fragment)
        return bool(self._extract_generic_interval_seconds(fragment) or any(self._is_timing_parameter_key(k) for k in values.keys()))

    def _dependency_ref_value(self, value: Any) -> str:
        if isinstance(value, dict):
            for key in ("id", "step_id", "source_step_id", "participant_id", "name"):
                item = str(value.get(key) or "").strip()
                if item:
                    return item
            return ""
        return str(value or "").strip()

    def _normalize_dependency_list_for_task(self, raw: Any, aliases: dict[str, str], removed_ids: set[str]) -> list[str]:
        out: list[str] = []
        for item in raw or []:
            ref = self._dependency_ref_value(item)
            if not ref:
                continue
            if ref in removed_ids or self._normalize_workflow_reference(ref) in {self._normalize_workflow_reference(x) for x in removed_ids}:
                continue
            canonical = aliases.get(ref) or aliases.get(self._normalize_workflow_reference(ref)) or aliases.get(self._canonical_step_reference(ref)) or self._canonical_step_reference(ref)
            if canonical and canonical not in out and canonical not in removed_ids:
                out.append(canonical)
        return out

    def _normalize_task_workflow_bindings(self, raw: Any, aliases: dict[str, str], removed_ids: set[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for item in raw or []:
            if not isinstance(item, dict):
                continue
            binding = dict(item)
            for key in ("source_step", "source_step_id", "from_step", "source"):
                if key in binding:
                    ref = self._dependency_ref_value(binding.get(key))
                    binding[key] = aliases.get(ref) or aliases.get(self._normalize_workflow_reference(ref)) or aliases.get(self._canonical_step_reference(ref)) or self._canonical_step_reference(ref)
            for key in ("target_step", "target_step_id", "to_step", "target"):
                if key in binding:
                    ref = self._dependency_ref_value(binding.get(key))
                    binding[key] = aliases.get(ref) or aliases.get(self._normalize_workflow_reference(ref)) or aliases.get(self._canonical_step_reference(ref)) or self._canonical_step_reference(ref)
            if str(binding.get("source_step") or binding.get("source_step_id") or "") in removed_ids:
                continue
            if str(binding.get("target_step") or binding.get("target_step_id") or "") in removed_ids:
                continue
            out.append(binding)
        return out

    def _materialize_schedule_policy_from_control_steps(
        self,
        *,
        schedule_policy: dict[str, Any],
        tasks: list[dict[str, Any]],
        participants: list[dict[str, Any]],
        runtime_parameters: dict[str, Any],
    ) -> dict[str, Any]:
        """Promote structural timing control steps into a durable task policy.

        The rule is capability-neutral: any step that declares timing fields can
        act as a control-plane step.  The generated task stores that timing on
        the task graph and the scheduler dispatches the non-controller payload
        steps when due.
        """
        policy = dict(schedule_policy or {})
        if policy.get("enabled") and str(policy.get("mode") or "") == "recurring":
            return policy

        controller_ids = self._derive_execution_controller_participant_ids(
            tasks=tasks,
            participants=participants,
            runtime_parameters=runtime_parameters,
        )
        if not controller_ids:
            return policy or {"enabled": False, "mode": "none"}

        interval_seconds = self._extract_interval_seconds_from_control_steps(
            tasks=tasks,
            controller_ids=controller_ids,
            runtime_parameters=runtime_parameters,
        )
        if not interval_seconds:
            return policy or {"enabled": False, "mode": "unresolved", "source": "control_step_timing"}

        now = self._now()
        return {
            "enabled": True,
            "mode": "recurring",
            "interval_seconds": int(interval_seconds),
            "next_run_at": now,
            "created_at": now,
            "state": "active",
            "source": "control_step_timing",
            "controller_participant_ids": controller_ids,
            "schedule_instance_id": "",
            "lifecycle_key": "",
        }

    def _extract_interval_seconds_from_control_steps(
        self,
        *,
        tasks: list[dict[str, Any]],
        controller_ids: list[str],
        runtime_parameters: dict[str, Any],
    ) -> int | None:
        controller_set = {str(x).strip() for x in controller_ids if str(x).strip()}
        candidates: list[str] = []

        for task in tasks or []:
            if not isinstance(task, dict):
                continue
            pid = str(task.get("participant_id") or task.get("participant") or task.get("agent_id") or "").strip()
            if pid not in controller_set:
                continue
            fragment = str(task.get("source_instruction_fragment") or task.get("objective") or "")
            if fragment:
                candidates.append(fragment)
            values = self._extract_runtime_parameters_from_instruction(fragment)
            for key, value in values.items():
                if self._is_timing_parameter_key(key):
                    candidates.append(f"{key}={value}")

        for key, value in (runtime_parameters or {}).items():
            key_text = str(key or "")
            base_key = key_text.rsplit(".", 1)[-1]
            if self._is_timing_parameter_key(base_key):
                candidates.append(f"{base_key}={value}")

        for candidate in candidates:
            seconds = self._extract_generic_interval_seconds(str(candidate))
            if seconds:
                return seconds
        return None

    def _is_timing_parameter_key(self, key: Any) -> bool:
        normalized = str(key or "").strip().casefold()
        if not normalized:
            return False
        return normalized in {
            "interval",
            "interval_seconds",
            "every",
            "repeat",
            "repeat_every",
            "schedule",
            "schedule_definition",
            "frequency",
        } or normalized.endswith("_interval") or normalized.endswith("_schedule")

    def _task_schedule_policy(self, task_graph: dict[str, Any]) -> dict[str, Any]:
        """Return durable schedule policy without mixing it with run pause state."""
        if not isinstance(task_graph, dict):
            return {"enabled": False, "mode": "none", "state": "none"}
        policy = task_graph.get("schedule_policy") if isinstance(task_graph.get("schedule_policy"), dict) else {}
        mode = str(policy.get("mode") or "none").strip().casefold()
        if mode in {"", "none"}:
            return {"enabled": False, "mode": "none", "state": "none"}
        out = dict(policy)
        out.setdefault("mode", mode)
        out.setdefault("state", "active" if bool(out.get("enabled")) else "paused")
        return out

    def _task_execution_type(self, task_graph: dict[str, Any]) -> str:
        explicit = str((task_graph or {}).get("execution_type") or "").strip().casefold()
        if explicit in {"one_shot", "scheduled"}:
            return explicit
        policy = self._task_schedule_policy(task_graph)
        return "scheduled" if str(policy.get("mode") or "none") not in {"", "none"} else "one_shot"

    def _is_scheduled_task_graph(self, task_graph: dict[str, Any]) -> bool:
        return self._task_execution_type(task_graph) == "scheduled"

    def _is_schedule_dispatch(self, provided_inputs: dict[str, Any] | None) -> bool:
        provided_inputs = provided_inputs or {}
        return bool(provided_inputs.get("_scheduled_payload_dispatch") or provided_inputs.get("_run_scheduled_payload_now"))

    def _execution_pause_reason(self, missing_inputs: list[dict[str, Any]], pending_action: dict[str, Any] | None) -> str:
        pending = pending_action if isinstance(pending_action, dict) else {}
        kind = str(pending.get("kind") or "").strip()
        fields = missing_inputs or []
        approval_fields = [f for f in fields if isinstance(f, dict) and self.delegation_runtime._is_approval_parameter_field(f)]
        if kind == "runtime_tool_human_confirmation" or approval_fields:
            return "runtime_approval_required"
        if fields:
            return "runtime_input_required"
        if kind == "validation_recovery":
            return "validation_recovery_required"
        return "runtime_interaction_required"

    def _maybe_activate_durable_schedule_on_manual_execution(
        self,
        *,
        task_name: str,
        task_graph: dict[str, Any],
        provided_inputs: dict[str, Any],
    ) -> dict[str, Any] | None:
        """When a task contains a timing controller, manual execution starts the schedule.

        Scheduled payload dispatches pass a private marker and are allowed to run
        the payload steps.  A user's direct execute request activates the durable
        schedule instead of running the payload once immediately.
        """
        if self._is_schedule_dispatch(provided_inputs):
            return None
        if not self._is_scheduled_task_graph(task_graph):
            return None
        policy = self._task_schedule_policy(task_graph)
        if str(policy.get("mode") or "") != "recurring":
            return None
        controllers = [str(x).strip() for x in (policy.get("controller_participant_ids") or []) if str(x).strip()]
        if not controllers:
            return None

        updated_graph = dict(task_graph)
        updated_policy = dict(policy)
        interval = int(updated_policy.get("interval_seconds") or 0)
        now = self._now()
        updated_policy["enabled"] = True
        updated_policy["state"] = "active"
        updated_policy["activated_at"] = now
        if interval > 0:
            try:
                from datetime import datetime, timedelta, timezone
                due_at = datetime.now(timezone.utc) + timedelta(seconds=interval)
                updated_policy["next_run_at"] = due_at.isoformat()
            except Exception:
                updated_policy["next_run_at"] = now
        elif not updated_policy.get("next_run_at"):
            updated_policy["next_run_at"] = now
        updated_policy.setdefault("schedule_instance_id", str(updated_graph.get("schedule_instance_id") or f"schedule_{task_name}"))
        updated_policy["lifecycle_key"] = str(updated_policy.get("schedule_instance_id") or f"schedule_{task_name}")
        updated_graph["schedule_policy"] = updated_policy
        updated_graph["schedule_instance_id"] = updated_policy.get("schedule_instance_id")
        updated_graph["updated_at"] = now
        _resolved_name, _existing_graph, _graph_path = self._read_task_graph_record(task_name)
        self._write_task_graph_record(str(_resolved_name or task_name), updated_graph, _graph_path)
        self._emit_schedule_observation(
            "schedule_activated",
            task_name=str(task_name),
            data={
                "interval_seconds": updated_policy.get("interval_seconds"),
                "next_run_at": updated_policy.get("next_run_at"),
                "controller_participant_ids": controllers,
            },
        )
        return {
            "action": "execute_task_graph",
            "origin": "auxiliary_brain",
            "status": "scheduled",
            "task_name": task_name,
            "message": "Task schedule activated. Payload execution will be dispatched by the runtime scheduler when due.",
            "final_answer": "Task schedule activated. Payload execution will be dispatched by the runtime scheduler when due.",
            "schedule_policy": updated_policy,
        }

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
            from auxiliary_brain.runtime.observability.runtime_console import emit_console_event
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
        has_schedule_language = any(token in lower for token in ("execution policy", "repeat", "every", "run every", "once at", "schedule", "interval"))
        if not has_schedule_language:
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
                "schedule_instance_id": "",
                "lifecycle_key": "",
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
