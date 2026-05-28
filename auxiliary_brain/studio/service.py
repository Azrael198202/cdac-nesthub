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
from ai_core.runtime.modeling.model_runtime_preflight import ModelRuntimePreflight
from auxiliary_brain.parameters.agent_parameter_contract import AgentParameterContractService
from ai_core.artifacts.artifact_registry import UploadedArtifactRegistry
from ai_core.artifacts.uploaded_artifact_contract import UploadedArtifactContractBuilder
from ai_core.artifacts.artifact_edit_service import ArtifactEditService
from ai_core.commands import CommandSetService
from ai_core.capabilities.capability_dispatcher import CapabilityDispatcher
from ai_core.media import ImageGenerationService
from ai_core.context.execution_reuse_store import ExecutionReuseStore
from ai_core.execution.parameter_resolution import ParameterResolutionPipeline, PreflightResolutionContext
from auxiliary_brain.studio.instruction_workflow_planner import InstructionWorkflowPlanner
from auxiliary_brain.studio.runtime_semantic_planner import RuntimeSemanticPlanner


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
        self.direct_capability_dispatcher = CapabilityDispatcher(handlers={
            "image_generation": self._handle_direct_image_generation,
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
                context={"session_id": session_id, "surface": "agent_studio"},
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
        if routed.action == "feedback_adaptation":
            return await self.handle_feedback(message, routed.name)
        artifact_edit = await self._maybe_handle_artifact_edit_message(message, uploaded_artifacts=uploaded_artifacts)
        if artifact_edit is not None:
            return artifact_edit
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
        final_answer = f"Generated image: ![{name}]({url})\nDownload: [{name}]({url})" if url else "Generated image material is available."
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

    def snapshot(self) -> dict[str, Any]:
        return {
            "origin": "auxiliary_brain",
            "community_id": self.community_id,
            "participants": self.store.list_json("generated/agents"),
            "task_graphs": self.store.list_json("generated/tasks"),
            "task_runs": self.store.list_json("generated/results"),
            "deliveries": self.store.list_json("deliveries"),
            "traces": self.store.list_json("traces/agent_delegation"),
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
            "execution_policy": "delegate_to_ai_core",
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
        }

    def create_task_graph(self, instruction: str, name: str | None = None, uploaded_artifacts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        graph_id = new_id("graph")
        task_name = name or graph_id
        participants = self.store.list_json("generated/agents")
        artifact_refs = self._resolve_uploaded_artifacts_for_instruction(instruction, uploaded_artifacts)
        explicit_runtime_parameters = self._extract_runtime_parameters_from_instruction(instruction)
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
        for generated_participant in workflow_plan.generated_participants:
            generated_participant.setdefault("created_at", self._now())
            pid = str(generated_participant.get("participant_id") or "").strip()
            if pid:
                self.store.write_json(f"generated/agents/{pid}.json", generated_participant)
        selected_ids = [p.get("participant_id") for p in workflow_plan.selected_participants]
        # Task graphs do not own durable parameter values.  Parameter schemas live
        # on participants, while uploaded artifact parameters are discovered from
        # the selected artifact during execution_preparation.  Keeping a blank
        # task-level contract here prevents stale values from leaking into
        # unrelated future runs and avoids referencing an undefined
        # participant-only parameter_contract.
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
            "tasks": workflow_plan.tasks,
            "instruction_coverage": workflow_plan.coverage,
            "workflow_planning": {
                "mode": workflow_plan.coverage.get("planning_mode"),
                "semantic_step_count": workflow_plan.coverage.get("semantic_step_count"),
                "semantic_plan_status": (semantic_plan.get("coverage_notes") or []),
                "generated_participant_ids": [p.get("participant_id") for p in workflow_plan.generated_participants],
                "step_count": len(workflow_plan.tasks),
                "coverage_status": workflow_plan.coverage.get("status"),
            },
            "final_synthesis_owner": "ai_core",
        }
        path = self.store.write_json(f"generated/tasks/{task_name}.json", payload)
        self._update_community()
        return {
            "action": "create_task_graph",
            "origin": "auxiliary_brain",
            "status": "completed",
            "graph_id": graph_id,
            "task_name": task_name,
            "path": str(path),
            "uploaded_artifacts": artifact_refs,
        }

    async def execute_task(self, task_name: str | None, provided_inputs: dict[str, Any] | None = None, instruction: str | None = None) -> dict[str, Any]:
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
        runtime_parameters.update(self._extract_runtime_parameters_from_instruction(instruction or ""))
        if isinstance(provided_inputs, dict):
            runtime_parameters.update({k: v for k, v in provided_inputs.items() if v not in (None, "", [], {})})
        preflight = self._preflight_runtime_parameters(task_graph, participants, runtime_parameters)
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
            reuse_response = await self._try_reused_task_execution(task_name, task_graph, participants, runtime_parameters)
            if reuse_response is not None:
                return reuse_response
            task_graph = dict(task_graph)
            task_graph["runtime_parameters"] = runtime_parameters
            result = await self.delegation_runtime.execute_task(task_graph, participants)
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
        return response

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
        """Extract explicit task-run parameters from the current instruction.

        This is generic syntax extraction, not domain logic. It supports common
        forms such as `name=value`, `name: value`, and `name 用 value`. Values are
        task-scoped and are not stored back onto the durable agent profile.
        """
        text = str(instruction or "")
        out: dict[str, Any] = {}
        for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*(?:=|:)\s*([^,;\n]+)", text):
            key = match.group(1).strip()
            value = match.group(2).strip().strip("'\"")
            if key and value:
                out[key] = value
        for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*(?:用|为|是|as)\s*([A-Za-z0-9_.:/-]+)", text, flags=re.I):
            key = match.group(1).strip()
            value = match.group(2).strip().strip("'\"")
            if key and value and key not in out:
                out[key] = value
        for match in re.finditer(r"\b(?:with|for|using)\s+([A-Za-z_][A-Za-z0-9_]*)\s+([^,;\n]+)", text, flags=re.I):
            key = match.group(1).strip()
            value = match.group(2).strip().strip("'\"")
            if key and value and key not in out and len(value.split()) <= 4:
                out[key] = value
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
        execution starts. This prevents the later execution phase from repeatedly
        pausing for file parameters and keeps task-specified parameters scoped to
        the current run.
        """
        all_missing: list[dict[str, Any]] = []
        analyses: list[dict[str, Any]] = []
        for participant in participants:
            artifacts = participant.get("uploaded_artifacts") or task_graph.get("uploaded_artifacts") or []
            if not artifacts:
                continue
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
            contract = self.uploaded_artifact_contract.build_contract(state=state, step=step, step_id="step_1")
            analyses.append(contract)
            for field in contract.get("missing_parameter_fields") or []:
                if isinstance(field, dict):
                    tagged = dict(field)
                    tagged.setdefault("resolution_layer", "resource_binding")
                    all_missing.append(tagged)
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
