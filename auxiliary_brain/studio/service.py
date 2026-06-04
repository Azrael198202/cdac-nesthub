from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import re

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
        self.direct_capability_dispatcher = CapabilityDispatcher(handlers={
            "image_generation": self._handle_direct_image_generation,
            "video_generation": self._handle_direct_video_generation,
        })
        self.store.ensure_workspace()
        self.community_id = self._ensure_community()

    async def handle_message(self, message: str, provided_inputs: dict[str, Any] | None = None, uploaded_artifacts: list[dict[str, Any]] | None = None, session_id: str | None = None) -> dict[str, Any]:
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
        if routed.action == "list_command_set":
            return self.list_command_set()
        if routed.action == "update_command_set":
            return self.update_command_set(message)
        if routed.action == "create_participant":
            return await self.create_participant(message, routed.name, uploaded_artifacts=uploaded_artifacts)
        if routed.action == "create_task":
            return self.create_task_graph(message, routed.name, uploaded_artifacts=uploaded_artifacts)

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

        # If the message is exactly a known task name, treat it as an execution
        # request. This keeps the UI natural: users can type `taskC` after
        # creating it, without falling into ordinary chat or re-planning.
        bare_task_name = self._resolve_bare_task_name(message)
        if routed.action == "chat" and bare_task_name:
            return await self.execute_task(bare_task_name, provided_inputs=provided_inputs, instruction=message)

        # Direct invocation of an already-created participant must stay in the
        # Agent/Task runtime instead of falling into the generic conversation
        # pipeline.  The decision is generic: it matches the user's text
        # against durable participant names, then creates a task-run wrapper so
        # the existing missing-parameter form, approval, resume, and registered
        # tool bridge are reused unchanged.
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
        core_pipeline_requested = self.natural_conversation.needs_core_conversation_pipeline(message)
        if routed.action == "feedback_adaptation" and core_pipeline_requested:
            return await self.natural_conversation.reply(message, latest_task=self._latest_task_name(), session_id=session_id)

        if routed.action == "feedback_adaptation":
            return await self.handle_feedback(message, routed.name)
        artifact_edit = await self._maybe_handle_artifact_edit_message(message, uploaded_artifacts=uploaded_artifacts)
        if artifact_edit is not None:
            return artifact_edit
        if not core_pipeline_requested:
            feedback = self.feedback_classifier.classify(message, fallback_target=self._latest_task_name())
            if feedback.get("matched"):
                return await self.handle_feedback(message, feedback.get("target_task"))
        return await self.natural_conversation.reply(message, latest_task=self._latest_task_name(), session_id=session_id)


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

    def delete_runtime_capability(self, tool_id: str, *, delete_artifacts: bool = False, delete_profiles: bool = False) -> dict[str, Any]:
        return self.registered_tool_service.delete_tool(tool_id, delete_artifacts=delete_artifacts, delete_profiles=delete_profiles)

    def _project_control_dispatch_task(self, *, instruction: str, task_name: str, workflow_plan: Any, runtime_parameters: dict[str, Any]) -> dict[str, Any]:
        """No fixed control-route projection is applied by Studio.

        Runtime behavior must come from the user-created task graph and the
        selected participants' generated schemas.  This prevents Studio from
        embedding capability-specific routes such as a particular trigger type
        or target parameter shape.
        """
        return {"applied": False, "reason": "no_static_projection"}

    def _extract_runtime_parameters_from_instruction(self, instruction: str) -> dict[str, Any]:
        """Extract explicit task-run parameters from user-authored text.

        Extraction is intentionally syntax based. It accepts simple assignment
        lines such as `name: value`, `- name: value`, or `name=value`, and avoids
        treating section headers such as `Parameters for X:` or `Step 1:` as
        runtime values. Values are task-scoped and are not stored back onto the
        durable agent profile.
        """
        text = str(instruction or "")
        out: dict[str, Any] = {}
        header_prefixes = {"step", "parameters", "parameter", "params"}
        assignment_line = re.compile(r"^\s*(?:[-*]\s*)?([A-Za-z_][A-Za-z0-9_]*)\s*(?:=|:)\s*(.+?)\s*$")
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            lowered = line.casefold()
            if any(lowered.startswith(prefix + " ") or lowered.startswith(prefix + ":") for prefix in header_prefixes):
                continue
            match = assignment_line.match(line)
            if not match:
                continue
            key = match.group(1).strip()
            value = match.group(2).strip().strip("'\"")
            if not key or not value:
                continue
            if value.endswith(":") and len(value.split()) <= 5:
                continue
            out[key] = value
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

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
