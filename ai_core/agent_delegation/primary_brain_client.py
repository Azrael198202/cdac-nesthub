from __future__ import annotations

from dataclasses import dataclass
import json
import asyncio
import re
from collections.abc import Callable
import uuid
from typing import Any

from ai_core.orchestration.workflow_runtime import WorkflowRuntime
from ai_core.llm.provider_router import ProviderRouter
from ai_core.llm.provider_handlers.utils import LLMJSONParseError, parse_json_content
from ai_core.runtime.governance import RuntimeCostPolicy
from presentation_brain import PresentationBrain, PresentationRequest
from auxiliary_brain.protocols.runtime_protocol import PrimaryRuntimeRequestEnvelope, PrimaryRuntimeExecutionPolicy
from ai_core.utils.safe_json import make_json_safe, safe_json_dumps


@dataclass
class AgentExecutionRequest:
    participant_id: str
    participant_name: str
    participant_instruction: str
    task_name: str
    task_instruction: str
    community_id: str
    shared_context: dict[str, Any]


@dataclass
class AgentExecutionResult:
    participant_id: str
    participant_name: str
    core_run_id: str
    status: str
    final_answer: str
    workflow_results: dict[str, Any]
    origin: str = "ai_core"
    pending_action: dict[str, Any] | None = None
    missing_inputs: list[dict[str, Any]] | None = None


class PrimaryBrainDelegationClient:
    """Delegates role work to the primary runtime.

    The auxiliary layer calls this client; the primary runtime performs parsing,
    planning, tool selection, execution, verification, and synthesis.
    """

    INTERNAL_OUTPUT_KEYS = {
        "agent_action_prompt_contract", "prompt_contract", "output_contract",
        "resource_bundle", "contract", "contracts", "instructions",
        "rules", "prompt", "system", "schema", "agent_execution_flow",
    }
    INTERNAL_OUTPUT_MARKERS = (
        "Use upstream input", "Return JSON", "Return valid JSON",
        "prompt_contract", "agent_action_prompt_contract", "planner_llm",
        "Agent actions and substeps planned", "locked fixed execution options",
        "workflow is blocked", "blocked step details",
    )

    def __init__(self, runtime: WorkflowRuntime | None = None) -> None:
        self.runtime = runtime or WorkflowRuntime()
        self.router = ProviderRouter()
        self.presentation_brain = PresentationBrain()

    async def execute_agent_request(self, request: AgentExecutionRequest, progress_callback: Callable[[dict[str, Any]], Any] | None = None) -> AgentExecutionResult:
        message = self._build_agent_message(request)
        core_run_id, state = await self.runtime.prepare(message)
        state.setdefault("runtime_options", {})["delegation_mode"] = True
        state.setdefault("runtime_options", {})["auto_approve_reviews"] = True
        if progress_callback:
            self.runtime.add_event_listener(core_run_id, progress_callback)
        try:
            await self._run_runtime_with_timeout(core_run_id, state, self.runtime.run_prepared(state))
        except Exception as exc:
            state["status"] = "failed"
            state["error"] = str(exc)
            state.setdefault("results", {})["runtime_error"] = {
                "status": "failed",
                "message": str(exc),
                "core_run_id": core_run_id,
            }
        finally:
            if progress_callback:
                self.runtime.remove_event_listener(core_run_id, progress_callback)
        final_answer = self._extract_final_answer(state)
        status = self._extract_status(state)
        pending_action = state.get("pending_action") if isinstance(state, dict) else None
        results = state.get("results", {}) if isinstance(state.get("results"), dict) else {}
        if self._should_attempt_direct_public_answer(
            request=request,
            status=status,
            final_answer=final_answer,
            pending_action=pending_action,
            results=results,
        ):
            fallback_answer = await self._direct_public_answer_fallback(request=request, core_run_id=core_run_id)
            if self._answer_has_result_material(fallback_answer):
                final_answer = fallback_answer
                status = "completed"
                results = dict(results)
                results["direct_public_answer_fallback"] = {
                    "status": "completed",
                    "final_answer": final_answer,
                    "execution_mode": "minimal_direct_answer",
                }
            else:
                status = "incomplete" if status == "completed" else status
        return AgentExecutionResult(
            participant_id=request.participant_id,
            participant_name=request.participant_name,
            core_run_id=core_run_id,
            status=status,
            final_answer=final_answer,
            workflow_results=results,
            pending_action=pending_action if isinstance(pending_action, dict) else None,
            missing_inputs=self._extract_missing_inputs(state),
        )



    async def execute_workflow_step_request(self, request: AgentExecutionRequest, progress_callback: Callable[[dict[str, Any]], Any] | None = None) -> AgentExecutionResult:
        """Execute one decomposed workflow step through the full primary runtime.

        The auxiliary brain owns graph decomposition and scheduling only.  It
        must not decide whether a step is a search, tool call, LLM answer, or
        runtime capability execution.  This entrypoint submits the step as a
        clean user-facing request so the primary runtime can run its normal
        input parsing, intent recognition, planning, execution, verification,
        and final synthesis pipeline.
        """
        return await self._execute_plain_primary_runtime_step(request, progress_callback=progress_callback)


    async def execute_intermediate_step(self, request: AgentExecutionRequest, progress_callback: Callable[[dict[str, Any]], Any] | None = None) -> AgentExecutionResult:
        """Execute a generated dataflow step with the smallest safe prompt.

        The step is generic: it receives an objective plus declared upstream
        results and returns only the user-facing step output. It avoids sending
        full task graphs or coordination metadata to the model. A pure final
        projection step with one upstream result is completed deterministically
        without using an LLM.
        """
        core_run_id = uuid.uuid4().hex[:12]
        if progress_callback:
            progress_callback({"type": "NODE_STARTED", "run_id": core_run_id, "node_id": "dataflow_step"})
            progress_callback({"type": "NODE_EXECUTING", "run_id": core_run_id, "node_id": "dataflow_step"})

        declared_dependencies = []
        if isinstance(request.shared_context, dict):
            raw_deps = request.shared_context.get("depends_on") or []
            declared_dependencies = raw_deps if isinstance(raw_deps, list) else [raw_deps]
        upstream = self._compact_declared_inputs((request.shared_context or {}).get("available_peer_results") or [])
        if declared_dependencies and not upstream:
            final_answer = "The generated step did not receive required upstream result material."
            if progress_callback:
                progress_callback({"type": "NODE_RESULT", "run_id": core_run_id, "node_id": "dataflow_step"})
                progress_callback({"type": "RUN_COMPLETED", "run_id": core_run_id})
            return AgentExecutionResult(
                participant_id=request.participant_id,
                participant_name=request.participant_name,
                core_run_id=core_run_id,
                status="failed",
                final_answer=final_answer,
                workflow_results={"dataflow_step": {"status": "failed", "final_answer": final_answer, "execution_mode": "missing_upstream_guard"}},
            )
        if not upstream and not declared_dependencies:
            return await self._execute_primary_runtime_for_standalone_step(request, progress_callback=progress_callback, core_run_id=core_run_id)

        projection = self._project_single_upstream_result_if_possible(request.participant_instruction, upstream)
        if projection is not None:
            status = "completed" if self._answer_has_result_material(projection) else "failed"
            if progress_callback:
                progress_callback({"type": "NODE_RESULT", "run_id": core_run_id, "node_id": "dataflow_step"})
                progress_callback({"type": "RUN_COMPLETED", "run_id": core_run_id})
            return AgentExecutionResult(
                participant_id=request.participant_id,
                participant_name=request.participant_name,
                core_run_id=core_run_id,
                status=status,
                final_answer=projection,
                workflow_results={"dataflow_step": {"status": status, "final_answer": projection, "execution_mode": "deterministic_projection"}},
            )

        schema = {
            "type": "object",
            "additionalProperties": False,
            "properties": {"final_answer": {"type": "string"}},
            "required": ["final_answer"],
        }
        user_prompt = self._build_lean_step_prompt(request.participant_instruction, upstream)
        execution_mode = "lean_llm"
        try:
            result = await self.router.generate_json(
                run_id=core_run_id,
                node_id="dataflow_step",
                adapter={
                    "adapter_id": "delegated_dataflow_step_lean",
                    "runtime_role": "intermediate_dataflow_step",
                    "route_name": "stable_synthesis",
                    "model_route_name": "stable_synthesis",
                    "provider_timeout_seconds": 180,
                    "max_provider_attempts": 1,
                    "json_repair_retry": False,
                    "accept_raw_text_as_final_answer": True,
                    "provider_options": {"temperature": 0, "num_predict": 320, "num_ctx": 1536, "think": False},
                    "prompt_policy": {"max_context_tokens": 720},
                    "max_prompt_chars": 1400,
                },
                prompt={"id": "delegated_dataflow_step_lean", "system": "Output only the requested result text. No JSON. No explanation."},
                rendered_user_prompt=user_prompt,
                schema=schema,
            )
            answer = result.get("final_answer") if isinstance(result, dict) else ""
            answer = self._normalize_public_step_answer(answer) if isinstance(answer, str) else ""
            status = "completed" if isinstance(answer, str) and self._answer_has_result_material(answer) else "failed"
            final_answer = answer.strip() if isinstance(answer, str) and answer.strip() else "Generated workflow step did not produce verified result material."
        except LLMJSONParseError as exc:
            recovered = self._recover_public_answer_from_invalid_json(exc)
            if recovered:
                status = "completed"
                final_answer = recovered
                execution_mode = "lean_llm_raw_text_fallback"
            else:
                status = "failed"
                final_answer = "Generated workflow step returned non-public or invalid material."
        except Exception as exc:
            recovered = self._recover_public_answer_from_provider_error(exc)
            if recovered:
                status = "completed"
                final_answer = recovered
                execution_mode = "lean_llm_error_text_fallback"
            else:
                status = "failed"
                final_answer = str(exc)
        if progress_callback:
            progress_callback({"type": "NODE_RESULT", "run_id": core_run_id, "node_id": "dataflow_step"})
            progress_callback({"type": "RUN_COMPLETED", "run_id": core_run_id})
        return AgentExecutionResult(
            participant_id=request.participant_id,
            participant_name=request.participant_name,
            core_run_id=core_run_id,
            status=status,
            final_answer=final_answer,
            workflow_results={"dataflow_step": {"status": status, "final_answer": final_answer, "execution_mode": execution_mode}},
        )



    async def _execute_primary_runtime_for_standalone_step(
        self,
        request: AgentExecutionRequest,
        *,
        progress_callback: Callable[[dict[str, Any]], Any] | None = None,
        core_run_id: str | None = None,
    ) -> AgentExecutionResult:
        """Run a standalone workflow step as a normal primary-runtime request.

        A standalone generated step has no upstream material to transform; it is
        simply a user-facing objective in the larger task graph.  Wrapping that
        objective in an internal ``AGENT_REQUEST=...`` envelope can make the
        primary runtime treat the step as coordination metadata instead of a
        real request, which then produces no exportable output for downstream
        steps.  This path therefore submits the clean objective text directly to
        the primary runtime while preserving delegation-mode progress and result
        extraction.

        The method is domain-neutral: it does not inspect the objective content
        or select a capability.  It only chooses the correct boundary between
        the auxiliary coordinator and the primary runtime for a source step.
        """
        if progress_callback and core_run_id:
            progress_callback({"type": "NODE_EXECUTING", "run_id": core_run_id, "node_id": "primary_runtime_standalone_step"})
        result = await self._execute_plain_primary_runtime_step(request, progress_callback=progress_callback)
        workflow_results = dict(result.workflow_results or {})
        workflow_results.setdefault("dataflow_step", {
            "status": result.status,
            "final_answer": result.final_answer,
            "execution_mode": "primary_runtime_standalone_step",
            "core_run_id": result.core_run_id,
            "exportable": self._answer_has_result_material(result.final_answer),
        })
        if progress_callback and core_run_id:
            progress_callback({"type": "NODE_RESULT", "run_id": core_run_id, "node_id": "primary_runtime_standalone_step"})
            progress_callback({"type": "RUN_COMPLETED", "run_id": core_run_id})
        return AgentExecutionResult(
            participant_id=request.participant_id,
            participant_name=request.participant_name,
            core_run_id=result.core_run_id,
            status=result.status,
            final_answer=result.final_answer,
            workflow_results=workflow_results,
            pending_action=result.pending_action,
            missing_inputs=result.missing_inputs,
            origin=result.origin,
        )

    async def _execute_plain_primary_runtime_step(
        self,
        request: AgentExecutionRequest,
        progress_callback: Callable[[dict[str, Any]], Any] | None = None,
    ) -> AgentExecutionResult:
        """Execute a step objective without an internal delegation envelope."""
        message = self._standalone_step_message(request)
        runtime_run_id, state = await self.runtime.prepare(message)
        state.setdefault("runtime_options", {})["delegation_mode"] = True
        state.setdefault("runtime_options", {})["auto_approve_reviews"] = True
        state.setdefault("runtime_options", {})["standalone_dataflow_source_step"] = True
        source_contract = request.shared_context.get("source_contract") if isinstance(request.shared_context, dict) else {}
        if isinstance(source_contract, dict) and source_contract:
            state.setdefault("runtime_options", {})["standalone_source_contract"] = source_contract
        state.setdefault("runtime_options", {})["isolated_delegated_step_context"] = True
        # A decomposed workflow step is a fresh primary-runtime request.  The
        # user session can still contain the parent task conversation, but that
        # rolling summary is coordination context and must not be injected into
        # the step's intent recognition/planning.  Peer material is passed
        # explicitly through shared_context when the dependency graph requires it.
        state["context_window"] = {"rolling_summary": "", "recent_turns": [], "open_items": [], "boundary": {}}
        if progress_callback:
            self.runtime.add_event_listener(runtime_run_id, progress_callback)
        try:
            await self._run_runtime_with_timeout(runtime_run_id, state, self.runtime.run_prepared(state))
        except Exception as exc:
            state["status"] = "failed"
            state["error"] = str(exc)
            state.setdefault("results", {})["runtime_error"] = {
                "status": "failed",
                "message": str(exc),
                "core_run_id": runtime_run_id,
            }
        finally:
            if progress_callback:
                self.runtime.remove_event_listener(runtime_run_id, progress_callback)
        results = state.get("results", {}) if isinstance(state.get("results"), dict) else {}
        final_answer = self._extract_final_answer(state)
        final_answer = self._extract_exportable_answer_from_results(results, fallback=final_answer)
        status = self._extract_status(state)
        if not self._answer_has_result_material(final_answer):
            presentation_answer = await self._present_delegated_step_output(
                run_id=runtime_run_id,
                request=request,
                state=state,
                results=results,
            )
            if self._answer_has_result_material(presentation_answer):
                final_answer = presentation_answer
                results = dict(results)
                results["delegated_step_presentation"] = {
                    "status": "completed",
                    "final_answer": final_answer,
                    "exportable": True,
                    "source": "presentation_brain",
                }
        if self._answer_has_result_material(final_answer):
            status = "completed"
        elif status in {"completed", "success", "succeeded", "ok"}:
            status = "failed"
        pending_action = state.get("pending_action") if isinstance(state, dict) else None
        return AgentExecutionResult(
            participant_id=request.participant_id,
            participant_name=request.participant_name,
            core_run_id=runtime_run_id,
            status=status,
            final_answer=final_answer,
            workflow_results=results,
            pending_action=pending_action if isinstance(pending_action, dict) else None,
            missing_inputs=self._extract_missing_inputs(state),
        )

    def _standalone_step_message(self, request: AgentExecutionRequest) -> str:
        """Build the isolated user request for one decomposed workflow step.

        The auxiliary layer owns task coordination and runtime parameters.  A
        standalone step sent back into ai_core must contain only its own
        instruction plus explicit public upstream results.  Runtime input values
        are excluded here so downstream capability parameters cannot change the
        upstream step's intent, planning, or source policy.
        """
        objective = str(request.participant_instruction or "").strip() or str(request.task_instruction or "").strip()
        context = request.shared_context if isinstance(request.shared_context, dict) else {}
        parts = [objective] if objective else []

        peer_results = context.get("available_peer_results") if isinstance(context.get("available_peer_results"), list) else []
        rendered_peers = []
        for item in peer_results[:10]:
            if not isinstance(item, dict):
                continue
            text = item.get("final_answer") or item.get("answer") or item.get("summary") or item.get("result")
            if isinstance(text, str) and self._answer_has_result_material(text):
                label = str(item.get("participant_name") or item.get("participant_id") or "upstream")
                rendered_peers.append(f"- {label}: {text.strip()}")
        if rendered_peers:
            parts.append("Available upstream results:\n" + "\n".join(rendered_peers))

        return "\n\n".join(part for part in parts if part).strip()


    async def _present_delegated_step_output(
        self,
        *,
        run_id: str,
        request: AgentExecutionRequest,
        state: dict[str, Any],
        results: dict[str, Any],
    ) -> str:
        """Render a delegated text-producing step through Presentation Brain.

        The primary runtime owns execution and verification.  Presentation Brain
        owns user-facing wording.  A multi-step workflow therefore exports the
        presentation result, not raw execution/debug material, when a downstream
        step asks for text such as a final answer or body.
        """
        if not isinstance(results, dict) or not results:
            return ""
        materials = self._presentation_materials_from_results(results)
        if not materials:
            return ""
        presentation_state = dict(state or {})
        presentation_state.setdefault("input", {"original_input": request.participant_instruction})
        try:
            presented = await self.presentation_brain.synthesize(PresentationRequest(
                run_id=run_id,
                node_id="delegated_step_presentation",
                original_input=str(request.participant_instruction or ""),
                state=presentation_state,
                materials=materials,
                trust_summary={"verified_real_execution": True},
                output_policy={"delivery_format": "text", "exportable": True},
            ))
        except Exception:
            return ""
        answer = str(getattr(presented, "final_answer", "") or "").strip()
        if self._answer_has_result_material(answer):
            return answer
        return ""

    def _presentation_materials_from_results(self, results: dict[str, Any]) -> list[dict[str, Any]]:
        materials: list[dict[str, Any]] = []
        for node_id, node in (results or {}).items():
            if not isinstance(node, dict):
                continue
            status = str(node.get("status") or node.get("execution_status") or node.get("_status") or "").casefold()
            if status in {"blocked", "failed", "error", "pending", "initializing", "planning", "planning_active", "ready_for_planning"}:
                continue
            material = self.presentation_brain.material_from_execution_step({
                "step_id": str(node_id),
                "status": status or "completed",
                "result": node,
            })
            if isinstance(material, dict) and material.get("content") not in (None, {}, [], ""):
                materials.append(material)
        return materials

    def _extract_exportable_answer_from_results(self, results: dict[str, Any], fallback: str = "") -> str:
        """Find a public terminal answer produced by the primary runtime.

        This intentionally avoids scanning arbitrary node values.  Pipeline node
        names, early parsing messages, planning summaries, and blocked workflow
        diagnostics are internal material and must never become downstream step
        output.  Only terminal/public containers may export text.
        """
        if self._answer_has_result_material(fallback):
            return str(fallback or "").strip()
        if not isinstance(results, dict):
            return ""

        candidates: list[tuple[str, Any]] = []
        terminal_nodes = ("final_synthesis", "conversation_output", "output", "synthesis", "dataflow_step")
        for node_key in terminal_nodes:
            node = results.get(node_key)
            if not isinstance(node, dict):
                continue
            if not self._node_can_export_public_material(node, node_key):
                continue
            for field in ("final_answer", "answer", "answer_material", "generated_content", "final_content", "content", "text", "result", "message"):
                if field in node:
                    candidates.append((f"{node_key}.{field}", node.get(field)))

        execution_node = results.get("execution")
        if isinstance(execution_node, dict) and self._node_can_export_public_material(execution_node, "execution"):
            for field in ("answer_material", "final_answer", "answer", "generated_content"):
                if field in execution_node:
                    candidates.append((f"execution.{field}", execution_node.get(field)))

        for _, value in candidates:
            text = self._public_scalar(value)
            if self._answer_has_result_material(text):
                return text.strip()
        return ""

    def _node_can_export_public_material(self, node: dict[str, Any], node_key: str = "") -> bool:
        status = str(node.get("status") or node.get("execution_status") or node.get("_status") or "").strip().casefold()
        if status in {"blocked", "failed", "error", "pending", "initializing", "planning", "planning_active", "ready_for_planning"}:
            return False
        if node.get("blocked_steps") or node.get("missing_inputs") or node.get("pending_action"):
            return False
        if node_key == "dataflow_step":
            exportable = node.get("exportable")
            if exportable is False:
                return False
            return status in {"completed", "success", "succeeded", "ok", ""}
        if node.get("exportable") or node.get("user_facing") or node.get("public") or node.get("public_output"):
            return True
        return node_key in {"final_synthesis", "conversation_output", "output", "synthesis"} and status in {"completed", "success", "succeeded", "ok", ""}

    def _public_scalar(self, value: Any) -> str:
        if isinstance(value, str):
            return self._normalize_public_step_answer(value)
        if isinstance(value, (int, float, bool)):
            return str(value)
        if isinstance(value, list):
            parts = [self._public_scalar(item) for item in value]
            return "\n".join([p for p in parts if self._answer_has_result_material(p)]).strip()
        if isinstance(value, dict):
            for key in ("final_answer", "answer", "answer_material", "generated_content", "final_content", "content", "text", "result", "message"):
                if key in value:
                    text = self._public_scalar(value.get(key))
                    if self._answer_has_result_material(text):
                        return text
        return ""

    def _recover_public_answer_from_invalid_json(self, exc: LLMJSONParseError) -> str:
        raw = str(getattr(exc, "raw_content", "") or getattr(exc, "candidate", "") or "").strip()
        return self._recover_public_answer_from_text(raw)

    def _recover_public_answer_from_provider_error(self, exc: Exception) -> str:
        # Some routers wrap parser errors into provider errors. This fallback is
        # intentionally conservative: it only accepts text that looks like a
        # user-facing answer and rejects internal diagnostics.
        text = str(exc or "").strip()
        return self._recover_public_answer_from_text(text)

    def _recover_public_answer_from_text(self, raw: str) -> str:
        text = self._normalize_public_step_answer(raw)
        if not text:
            return ""
        try:
            parsed = parse_json_content(text)
            value = parsed.get("final_answer") or parsed.get("answer") or parsed.get("result")
            if isinstance(value, str) and self._answer_has_result_material(value):
                return self._compact_text(self._normalize_public_step_answer(value), 4000)
        except Exception:
            pass
        # If the model returned plain text instead of the requested JSON wrapper,
        # accept it as the step result only when it is public answer material.
        cleaned = text
        cleaned = re.sub(r"^.*?Last error:\s*", "", cleaned, flags=re.DOTALL).strip() if "Last error:" in cleaned else cleaned
        if self._answer_has_result_material(cleaned):
            return self._compact_text(self._normalize_public_step_answer(cleaned), 4000)
        return ""

    def _normalize_public_step_answer(self, raw: Any) -> str:
        text = str(raw or "").strip()
        if not text:
            return ""
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()
        try:
            parsed = parse_json_content(text)
            for key in ("final_answer", "answer", "result", "message", "text"):
                value = parsed.get(key) if isinstance(parsed, dict) else None
                if isinstance(value, str) and value.strip():
                    return value.strip()
        except Exception:
            pass
        match = re.search(r'^\s*\{\s*["\'](?:final_answer|answer|result|message|text)["\']\s*:\s*["\'](?P<value>.*)', text, flags=re.DOTALL)
        if match:
            value = match.group("value").strip()
            # Remove only a real trailing JSON terminator.  Do not strip useful
            # content after the last quote because lenient routers may return a
            # truncated wrapper whose value is the actual public answer.
            value = re.sub(r'["\']\s*\}\s*$', "", value, flags=re.DOTALL).strip()
            if value:
                return value
        return text

    def _compact_declared_inputs(self, value: Any) -> list[dict[str, str]]:
        items = value if isinstance(value, list) else []
        compact: list[dict[str, str]] = []
        diagnostic_markers = (
            "no real llm provider",
            "model request timed out",
            "provider=",
            "runtime/configs/models/providers.yaml",
        )
        for item in items:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "").casefold()
            if status and status not in {"completed", "success"}:
                continue
            text = str(item.get("final_answer_summary") or item.get("final_answer") or item.get("result") or "").strip()
            if not text:
                continue
            lowered = text.casefold()
            if any(marker in lowered for marker in diagnostic_markers):
                continue
            if not self._answer_has_result_material(text):
                continue
            compact.append({
                "name": self._compact_text(item.get("participant_name") or item.get("participant_id") or "input", 80),
                "text": self._compact_text(text, 1200),
            })
        return compact


    def _compact_text(self, value: Any, max_chars: int = 800) -> str:
        text = str(value or "").strip()
        text = re.sub(r"\s+", " ", text)
        if len(text) <= max_chars:
            return text
        return text[: max(0, max_chars - 3)].rstrip() + "..."

    def _build_lean_step_prompt(self, objective: str, upstream: list[dict[str, str]]) -> str:
        lines = ["TASK:", self._compact_text(objective, 220), "INPUT:"]
        for idx, item in enumerate(upstream, 1):
            text = item.get("text") or ""
            lines.append(f"{idx}. {text}")
        lines.append("Output only the final user-facing text.")
        return "\n".join(lines)

    def _project_single_upstream_result_if_possible(self, objective: str, upstream: list[dict[str, str]]) -> str | None:
        if len(upstream) != 1:
            return None
        text = str(objective or "").lower()
        words = re.findall(r"[a-z]+", text)
        word_set = set(words)
        project_terms = {"return", "show", "provide", "output", "answer", "result", "final", "only"}
        transform_terms = {"convert", "rewrite", "summarize", "summarise", "analyze", "analyse", "compare", "merge", "combine", "extract", "format", "transform"}
        if word_set & transform_terms:
            return None
        if word_set & project_terms:
            return upstream[0].get("text", "").strip()
        return None

    async def resume_agent_request(self, result_payload: dict[str, Any], progress_callback: Callable[[dict[str, Any]], Any] | None = None, provided_inputs: dict[str, Any] | None = None) -> AgentExecutionResult:
        """Resume a paused primary-runtime participant run from its saved checkpoint.

        This is a durable continuation path: the auxiliary layer passes the
        previously returned participant result, including its core_run_id. The
        primary runtime loads its own checkpoint and continues from the blocked
        node instead of starting the participant from the beginning.
        """
        core_run_id = str(result_payload.get("core_run_id") or "").strip()
        if not core_run_id:
            return AgentExecutionResult(
                participant_id=str(result_payload.get("participant_id") or ""),
                participant_name=str(result_payload.get("participant_name") or "participant"),
                core_run_id="",
                status="failed",
                final_answer="Missing core_run_id; unable to resume participant execution.",
                workflow_results={},
            )

        state = self.runtime.checkpoints.load(core_run_id)
        if not state:
            return AgentExecutionResult(
                participant_id=str(result_payload.get("participant_id") or ""),
                participant_name=str(result_payload.get("participant_name") or "participant"),
                core_run_id=core_run_id,
                status="failed",
                final_answer="Primary runtime checkpoint was not found; cannot resume without restarting.",
                workflow_results={},
            )

        pending = state.get("pending_action") if isinstance(state, dict) else None
        if progress_callback:
            self.runtime.add_event_listener(core_run_id, progress_callback)
        try:
            if isinstance(pending, dict):
                await self._resume_state_direct(core_run_id, state, pending, provided_inputs=provided_inputs)
        finally:
            if progress_callback:
                self.runtime.remove_event_listener(core_run_id, progress_callback)
        final_state = state

        return AgentExecutionResult(
            participant_id=str(result_payload.get("participant_id") or ""),
            participant_name=str(result_payload.get("participant_name") or "participant"),
            core_run_id=core_run_id,
            status=self._extract_status(final_state),
            final_answer=self._extract_final_answer(final_state),
            workflow_results=final_state.get("results", {}) if isinstance(final_state, dict) else {},
            pending_action=(final_state.get("pending_action") if isinstance(final_state, dict) and isinstance(final_state.get("pending_action"), dict) else None),
            missing_inputs=self._extract_missing_inputs(final_state) if isinstance(final_state, dict) else [],
        )


    async def _resume_state_direct(self, core_run_id: str, state: dict[str, Any], pending: dict[str, Any], provided_inputs: dict[str, Any] | None = None) -> None:
        """Continue a saved primary-runtime state without restarting earlier nodes."""
        kind = str(pending.get("kind") or "")
        retry_index = pending.get("retry_node_index")
        node_id = pending.get("node_id")

        provided_inputs = provided_inputs if isinstance(provided_inputs, dict) else {}

        if kind in {"secret_input", "optional_credential_choice"}:
            modified = dict(provided_inputs) if provided_inputs else self._build_resume_modified_result(pending)
            action = str(modified.get("action") or modified.get("choice") or "").strip().lower()
            skip_requested = bool(modified.get("skip_credential")) or action in {"skip", "skip_credential", "continue_without_key", "continue_without_credential"}
            secret_key = str(modified.get("secret_key") or modified.get("field") or pending.get("secret_key") or "runtime_access_key")
            secret_value = str(modified.get("value") or modified.get("credential") or modified.get("api_key") or "")
            if skip_requested:
                prefs = state.setdefault("runtime_execution_preferences", {})
                prefs["credential_mode"] = "skip"
                prefs["skip_credential_candidates"] = True
                prefs.setdefault("skipped_secret_keys", [])
                if secret_key not in prefs["skipped_secret_keys"]:
                    prefs["skipped_secret_keys"].append(secret_key)
                state.setdefault("runtime_credentials", {})[secret_key] = "skipped"
            else:
                if not secret_value:
                    state.setdefault("runtime_execution_preferences", {})["credential_mode"] = "missing"
                    self._clear_waiting_state(state)
                    self.runtime.checkpoints.save(core_run_id, state)
                    return
                from ai_core.secrets.secret_store import SecretStore
                SecretStore().set(secret_key, secret_value)
                state.setdefault("runtime_credentials", {})[secret_key] = "***"
                state.setdefault("runtime_execution_preferences", {})["credential_mode"] = "provided"
            if node_id:
                state.get("results", {}).pop(node_id, None)
            if retry_index is not None:
                state["node_index"] = int(retry_index)

        elif kind == "validation_recovery" and node_id:
            original = state.get("results", {}).get(node_id, {})
            repaired = self._merge_human_inputs_into_result(original, provided_inputs)
            state.setdefault("results", {})[node_id] = repaired
            state.setdefault("human_information_history", []).append({
                "node_id": node_id,
                "provided": provided_inputs,
                "recovery_kind": kind,
            })
            if retry_index is not None:
                state["node_index"] = int(retry_index) + 1

        elif kind in {"collect_runtime_parameters", "runtime_parameter_input", "uploaded_artifact_parameters"}:
            clean_inputs = self._clean_runtime_inputs(provided_inputs)
            state.setdefault("human_information_history", []).append({
                "node_id": node_id,
                "provided": clean_inputs,
                "recovery_kind": kind,
            })
            state.setdefault("runtime_parameters", {}).update(clean_inputs)
            state.setdefault("runtime_inputs", {}).update(clean_inputs)
            state.setdefault("provided_inputs", {}).update(clean_inputs)
            # Runtime parameters change execution_preparation and validation.
            # Remove downstream cached results and resume from preparation so
            # uploaded-artifact contracts are rebuilt with the submitted values.
            results = state.setdefault("results", {})
            for key in ("execution_preparation", "pre_execution_validation", "execution", "result_verification", "feedback_repair", "final_synthesis", "output"):
                results.pop(key, None)
            prep_index = self._find_workflow_node_index(state, "execution_preparation")
            if prep_index is not None:
                state["node_index"] = prep_index
            elif retry_index is not None:
                state["node_index"] = max(0, int(retry_index) - 2)

        elif kind == "human_information_required":
            state.setdefault("human_information_history", []).append({
                "node_id": node_id,
                "provided": provided_inputs,
                "recovery_kind": kind,
            })
            if node_id:
                existing = state.get("results", {}).get(node_id, {})
                state.setdefault("results", {})[node_id] = self._merge_human_inputs_into_result(existing, provided_inputs)
            if retry_index is not None:
                state["node_index"] = int(retry_index) + 1

        else:
            if node_id:
                state.get("results", {}).pop(node_id, None)
            if retry_index is not None:
                state["node_index"] = int(retry_index)

        self._clear_waiting_state(state)
        state["status"] = "resuming"
        self.runtime.checkpoints.save(core_run_id, state)
        await self.runtime._emit(core_run_id, {
            "type": "DURABLE_RESUME_STARTED",
            "title": "Durable resume started",
            "message": "Continuing from the saved primary-runtime checkpoint with provided human input.",
            "node_id": node_id,
            "provided_input_keys": list(provided_inputs.keys()),
            "progress": state.get("progress", 0),
            "origin": "ai_core",
        })
        await self._run_runtime_with_timeout(core_run_id, state, self.runtime._continue(state))

    async def _run_runtime_with_timeout(self, core_run_id: str, state: dict[str, Any], awaitable) -> None:
        snapshot = RuntimeCostPolicy().snapshot(state)
        timeout_seconds = self._compute_primary_runtime_timeout_seconds(state, snapshot)
        try:
            await asyncio.wait_for(awaitable, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            state["status"] = "failed"
            state["timeout"] = {
                "status": "timeout",
                "timeout_seconds": timeout_seconds,
                "current_node_index": state.get("node_index"),
            }
            self._clear_waiting_state(state)
            state.setdefault("results", {})["runtime_timeout_finalizer"] = {
                "status": "failed",
                "reason": "Primary runtime exceeded the configured execution timeout and was finalized instead of remaining in running state.",
                "timeout_seconds": timeout_seconds,
            }
            self.runtime.checkpoints.save(core_run_id, state)
            await self.runtime._emit(core_run_id, {
                "type": "RUN_FAILED",
                "title": "Primary runtime timed out",
                "message": "Execution exceeded the configured timeout and was finalized as failed.",
                "origin": "ai_core",
            })



    def _compute_primary_runtime_timeout_seconds(self, state: dict[str, Any], snapshot: Any) -> int:
        """Compute a whole-run timeout from generic runtime structure.

        The previous fixed 210s budget was smaller than a normal local-model run
        on Windows/Ollama, where several JSON nodes may each need tens of seconds.
        This budget is domain-neutral: it only looks at remaining workflow nodes,
        stage/provider timeout hints, and environment-configured operation budget.
        """
        base_timeout = max(60, int(getattr(snapshot, "operation_timeout_seconds", 180) or 180))
        workflow = state.get("workflow") if isinstance(state, dict) else {}
        nodes = workflow.get("nodes") if isinstance(workflow, dict) else []
        node_index = int(state.get("node_index") or 0) if isinstance(state, dict) else 0
        remaining_nodes = max(1, len(nodes) - node_index) if isinstance(nodes, list) else 1

        stage_timeouts = getattr(snapshot, "stage_timeouts", {}) or {}
        stage_budget = 0
        if isinstance(stage_timeouts, dict):
            for node in (nodes[node_index:] if isinstance(nodes, list) else []):
                node_id = str((node or {}).get("id") or "")
                stage_budget += int(stage_timeouts.get(node_id) or 0)

        # Local LLM JSON nodes can be slow on Windows/CPU. Give each remaining
        # node a generic minimum budget, without knowing or hardcoding the task domain.
        per_node_floor = int(state.get("runtime_node_timeout_floor_seconds") or 180)
        structural_budget = remaining_nodes * per_node_floor

        return max(base_timeout + 60, stage_budget + 60, structural_budget + 60)

    def _clean_runtime_inputs(self, provided_inputs: dict[str, Any]) -> dict[str, Any]:
        clean: dict[str, Any] = {}
        if not isinstance(provided_inputs, dict):
            return clean
        for raw_key, value in provided_inputs.items():
            key = str(raw_key or "").strip()
            if not key or key in {"action", "choice", "secret_key", "value", "credential", "api_key"}:
                continue
            if isinstance(value, str) and value == "":
                continue
            clean[key] = value
        return clean

    def _find_workflow_node_index(self, state: dict[str, Any], node_id: str) -> int | None:
        workflow = state.get("workflow") if isinstance(state, dict) else None
        nodes = workflow.get("nodes") if isinstance(workflow, dict) and isinstance(workflow.get("nodes"), list) else []
        for idx, node in enumerate(nodes):
            if isinstance(node, dict) and str(node.get("id") or node.get("node_id") or "") == str(node_id):
                return idx
        return None

    def _clear_waiting_state(self, state: dict[str, Any]) -> None:
        state.pop("pending_action", None)
        state.pop("missing_inputs", None)
        state.pop("waiting_input", None)
        state.pop("requires_key", None)

    def _merge_human_inputs_into_result(self, original: Any, provided_inputs: dict[str, Any]) -> Any:
        """Merge form values into a JSON-like node result without domain rules.

        Supports simple field names and dotted paths such as
        ``items.0.value_type``. Empty values are ignored so users can submit
        only the fields they want to repair.
        """
        import copy

        result = copy.deepcopy(original) if isinstance(original, (dict, list)) else {}
        if not isinstance(provided_inputs, dict):
            return result
        for raw_key, raw_value in provided_inputs.items():
            key = str(raw_key or "").strip()
            if not key:
                continue
            value = raw_value
            if isinstance(value, str) and value == "":
                continue
            self._assign_path_value(result, key, value)
        return result

    def _assign_path_value(self, target: Any, path: str, value: Any) -> None:
        parts = [p for p in path.replace("[", ".").replace("]", "").split(".") if p != ""]
        if not parts:
            return
        current = target
        for part in parts[:-1]:
            if isinstance(current, list):
                try:
                    idx = int(part)
                except Exception:
                    return
                while len(current) <= idx:
                    current.append({})
                if current[idx] is None:
                    current[idx] = {}
                current = current[idx]
            elif isinstance(current, dict):
                nxt = current.get(part)
                if not isinstance(nxt, (dict, list)):
                    nxt = {}
                    current[part] = nxt
                current = nxt
            else:
                return
        last = parts[-1]
        if isinstance(current, list):
            try:
                idx = int(last)
            except Exception:
                return
            while len(current) <= idx:
                current.append(None)
            current[idx] = value
        elif isinstance(current, dict):
            current[last] = value

    def _collect_null_paths(self, value: Any, prefix: str = "") -> list[str]:
        paths: list[str] = []
        if isinstance(value, dict):
            for key, child in value.items():
                child_prefix = f"{prefix}.{key}" if prefix else str(key)
                if child is None:
                    paths.append(child_prefix)
                else:
                    paths.extend(self._collect_null_paths(child, child_prefix))
        elif isinstance(value, list):
            for idx, child in enumerate(value):
                child_prefix = f"{prefix}.{idx}" if prefix else str(idx)
                if child is None:
                    paths.append(child_prefix)
                else:
                    paths.extend(self._collect_null_paths(child, child_prefix))
        return paths

    def _build_resume_modified_result(self, pending: dict[str, Any]) -> dict[str, Any]:
        kind = str(pending.get("kind") or "")
        request = pending.get("request") if isinstance(pending.get("request"), dict) else {}
        secret_key = str(pending.get("secret_key") or request.get("secret_key") or request.get("provider") or "runtime_access_key")
        try:
            from ai_core.secrets.secret_store import SecretStore
            secret_value = SecretStore().get(secret_key)
        except Exception:
            secret_value = None
        if kind == "optional_credential_choice":
            return {"action": "provide_credential", "choice": "provide_credential", "secret_key": secret_key, "value": secret_value or "", "credential": secret_value or "", "api_key": secret_value or ""}
        if kind == "secret_input":
            return {"secret_key": secret_key, "value": secret_value or ""}
        return {"action": "approve", "secret_key": secret_key, "value": secret_value or ""}

    async def synthesize_delegated_results(
        self,
        *,
        task_name: str,
        task_instruction: str,
        agent_results: list[AgentExecutionResult],
        shared_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create the final delegated answer inside the primary runtime boundary.

        This is intentionally not a new task workflow. The participant workflows
        have already executed. Starting another full workflow for synthesis may
        accidentally treat the synthesis prompt as a fresh executable task.
        Here the primary runtime performs a generic, deterministic synthesis over
        completed participant results only.
        """
        core_run_id = uuid.uuid4().hex[:12]
        usable_results = self._usable_agent_results(agent_results)
        failed_results = [r for r in agent_results if str(r.status or "").lower() != "completed"]
        if usable_results:
            final_answer = await self._compose_or_escalate_delegated_final_answer(
                core_run_id=core_run_id,
                task_name=task_name,
                task_instruction=task_instruction,
                agent_results=usable_results,
                shared_context=shared_context or {},
            )
        else:
            # No participant produced verified user-facing material. Do not feed
            # planner/status text back into an LLM for synthesis, because that can
            # turn internal planning messages into fake final answers.
            final_answer = self._compose_delegated_final_answer(
                task_name=task_name,
                task_instruction=task_instruction,
                agent_results=agent_results,
            )
        return {
            "origin": "ai_core",
            "core_run_id": core_run_id,
            "status": "partial_failed" if failed_results else ("completed" if usable_results else "failed"),
            "final_answer": final_answer,
            "workflow_results": {
                "delegated_synthesis": {
                    "status": "completed",
                    "participant_count": len(agent_results),
                    "used_participant_count": len(usable_results),
                    "omitted_participant_count": max(0, len(agent_results) - len(usable_results)),
                    "failed_participant_count": len(failed_results),
                }
            },
        }

    def _should_attempt_direct_public_answer(
        self,
        *,
        request: AgentExecutionRequest,
        status: str,
        final_answer: str,
        pending_action: Any,
        results: dict[str, Any] | None = None,
    ) -> bool:
        """Use a small direct-answer fallback only for non-artifact participants.

        This does not hard-code any domain. It handles the generic failure mode
        where the primary runtime stops at an internal planning message instead
        of producing public answer material.
        """
        if isinstance(pending_action, dict):
            return False
        context = request.shared_context if isinstance(request.shared_context, dict) else {}
        artifact_binding = context.get("artifact_binding") if isinstance(context.get("artifact_binding"), dict) else {}
        if artifact_binding.get("available"):
            return False
        if self._shared_context_has_missing_required_inputs(context):
            return False
        if self._results_contain_blocking_execution_failure(results):
            return False
        # A planned runtime path may still finish with an internal planning
        # summary instead of public material.  If there is no blocking failure
        # and the final answer is not usable, allow one small material fallback.
        if str(status or "").lower() in {"requires_input", "requires_key", "paused", "failed", "timeout", "blocked", "waiting_for_input"}:
            return False
        return not self._answer_has_result_material(final_answer)

    def _results_show_runtime_execution_path(self, results: dict[str, Any] | None) -> bool:
        """Return True once the primary runtime has entered a planned execution path.

        Direct public-answer fallback is only for requests that never produced a
        runtime execution contract.  If planning/execution nodes exist, their
        blocked/failed status must be surfaced or repaired instead of being
        replaced by a minimal direct answer.
        """
        if not isinstance(results, dict):
            return False
        execution_node_keys = {"agent_action_planning", "execution_preparation", "pre_execution_validation", "execution", "result_verification", "feedback_repair", "final_synthesis"}
        return any(key in results for key in execution_node_keys)

    def _results_contain_blocking_execution_failure(self, results: dict[str, Any] | None) -> bool:
        """Return True when primary execution explicitly rejected its material.

        A direct public-answer fallback is useful for pure direct responses, but
        it must not convert a failed execution-quality gate into a successful
        answer.  The check is structural and generic: it looks for failure
        states/codes in the runtime result tree, not for task names or domains.
        """
        if not isinstance(results, dict):
            return False

        blocking_statuses = {"failed_quality_gate", "requires_input", "waiting_for_input", "blocked", "failed_by_dependency", "content_generation_failed"}
        blocking_codes = {"generated_answer_quality_failed", "content_generation_failed"}

        def walk(value: Any) -> bool:
            if isinstance(value, dict):
                status = str(value.get("status") or value.get("_status") or "").casefold()
                if status in blocking_statuses or status.endswith("_failed"):
                    return True
                blocked_steps = value.get("blocked_steps")
                if isinstance(blocked_steps, list) and blocked_steps:
                    return True
                error = value.get("error")
                if isinstance(error, dict) and str(error.get("code") or "").casefold() in blocking_codes:
                    return True
                if str(value.get("code") or "").casefold() in blocking_codes:
                    return True
                for nested in value.values():
                    if walk(nested):
                        return True
            elif isinstance(value, list):
                for nested in value:
                    if walk(nested):
                        return True
            return False

        return walk(results)

    def _shared_context_has_missing_required_inputs(self, context: dict[str, Any]) -> bool:
        """Return True when the selected execution context still needs user input.

        This guard is structural.  It prevents a public-answer fallback from
        converting a paused/blocked run into a successful answer, without
        relying on any domain or example phrase.
        """
        if not isinstance(context, dict):
            return False
        containers = [context]
        for key in ("agent_parameters", "parameter_contract", "execution_contract", "input_contract"):
            value = context.get(key)
            if isinstance(value, dict):
                containers.append(value)
        for container in containers:
            for key in ("missing_inputs", "missing_information", "blocking_missing_information", "missing_required"):
                value = container.get(key) if isinstance(container, dict) else None
                if isinstance(value, list) and value:
                    return True
                if isinstance(value, dict) and any(v not in (None, "", [], {}) for v in value.values()):
                    return True
        return False

    def _public_runtime_inputs(self, values: dict[str, Any]) -> dict[str, Any]:
        """Keep only user-confirmed scalar/list/dict inputs for direct material fallback.

        The runtime input map may contain participant identifiers, planner state,
        graph metadata, and values intended for other participants.  This generic
        filter keeps the fallback prompt focused on confirmed public inputs
        without depending on any task name, domain, or example phrase.
        """
        if not isinstance(values, dict):
            return {}
        excluded_exact = {
            "participant_name", "participant_id", "agent_name", "agent_id",
            "objective", "capability", "intent", "task_name", "community_id",
            "run_id", "node_id", "step_id", "timestamp", "system_clock",
            "timezone", "t",
        }
        excluded_fragments = (
            "trace", "runtime", "planner", "execution", "workflow",
            "graph", "status", "message", "source_step", "substep",
        )
        out: dict[str, Any] = {}
        for raw_key, value in values.items():
            key = str(raw_key or "").strip()
            if not key or key in excluded_exact:
                continue
            low = key.lower()
            if any(fragment in low for fragment in excluded_fragments):
                continue
            if value in (None, "", [], {}):
                continue
            if isinstance(value, (str, int, float, bool, list, dict)):
                out[key] = value
        return out

    async def _direct_public_answer_fallback(self, *, request: AgentExecutionRequest, core_run_id: str) -> str:
        """Ask the configured model for one concise public answer.

        The prompt is intentionally small so local models can run it. It receives
        only the participant objective, the task instruction, explicit runtime
        parameters, dependency summaries, and a current timestamp. The model is
        not asked to plan or choose tools.
        """
        try:
            from datetime import datetime, timezone
            payload: dict[str, Any] = {
                "participant_name": request.participant_name,
                "participant_objective": request.participant_instruction,
                "task_instruction": request.task_instruction,
                "current_timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            }
            context = request.shared_context if isinstance(request.shared_context, dict) else {}
            params = context.get("agent_parameters") if isinstance(context.get("agent_parameters"), dict) else {}
            values = params.get("values") if isinstance(params.get("values"), dict) else {}
            public_values = self._public_runtime_inputs(values) if isinstance(values, dict) else {}
            if public_values:
                payload["runtime_inputs"] = public_values
            peers = context.get("available_peer_results")
            if isinstance(peers, list) and peers:
                payload["upstream_results"] = peers[:8]
            schema = {
                "type": "object",
                "properties": {"final_answer": {"type": "string"}},
                "required": ["final_answer"],
                "additionalProperties": True,
            }
            result = await self.router.generate_json(
                run_id=core_run_id,
                node_id="direct_public_answer_fallback",
                adapter={
                    "adapter_id": "direct_public_answer_fallback",
                    "route_name": "stable_synthesis",
                    "provider_route": ["ollama", "openai"],
                    "provider_timeout_seconds": 120,
                    "max_provider_attempts": 1,
                    "max_prompt_tokens": 900,
                    "provider_options": {"temperature": 0.25, "num_predict": 900, "num_ctx": 2048, "think": False},
                },
                prompt={
                    "system": (
                        "Return JSON only with final_answer. "
                        "Produce the user-facing final deliverable directly. "
                        "Use runtime_inputs as confirmed constraints when present. "
                        "Do not describe planning, tools, routing, readiness, or execution steps. "
                        "Use only the provided input and timestamp."
                    )
                },
                rendered_user_prompt=safe_json_dumps(payload, separators=(",", ":")),
                schema=schema,
            )
            answer = result.get("final_answer") if isinstance(result, dict) else ""
            return str(answer or "").strip()
        except Exception:
            return ""

    def _build_agent_message(self, request: AgentExecutionRequest) -> str:
        import json

        context = request.shared_context or {}
        if isinstance(context, dict) and str(context.get("workflow_step_type") or "") == "semantic_intermediate_step":
            # Defensive boundary: generated workflow steps must be submitted as
            # clean user requests even if an older caller accidentally routes them
            # through execute_agent_request.  This prevents task-level runtime
            # parameters and unresolved workflow templates from contaminating the
            # step's ai_core planning.
            return self._standalone_step_message(request)

        # Agent execution must be local to the participant.  Task-level routing
        # data, graph metadata, and policy envelopes belong to the auxiliary
        # coordinator and final synthesis, not to each participant LLM stage.
        # Keeping this payload small prevents local JSON models from copying
        # unrelated task text into workflow or execution prompts.
        local_context = {}
        if isinstance(context, dict):
            for key in ("relationship", "depends_on", "agent_parameters", "available_peer_results"):
                value = context.get(key)
                if value not in (None, "", [], {}):
                    if key == "agent_parameters" and self._contains_unresolved_workflow_template(value):
                        value = self._remove_unresolved_parameter_values(value)
                    if value not in (None, "", [], {}):
                        local_context[key] = value
        payload = {
            "participant_name": request.participant_name,
            "objective": (request.participant_instruction or "").strip(),
        }
        if local_context:
            payload["context"] = local_context
        return "AGENT_REQUEST=" + safe_json_dumps(payload, separators=(",", ":"))

    def _contains_unresolved_workflow_template(self, value: Any) -> bool:
        if isinstance(value, str):
            return "{{" in value and "}}" in value
        if isinstance(value, dict):
            return any(self._contains_unresolved_workflow_template(v) for v in value.values())
        if isinstance(value, list):
            return any(self._contains_unresolved_workflow_template(v) for v in value)
        return False

    def _remove_unresolved_parameter_values(self, value: Any) -> Any:
        if isinstance(value, dict):
            cleaned = {}
            for key, item in value.items():
                if self._contains_unresolved_workflow_template(item):
                    continue
                cleaned[key] = self._remove_unresolved_parameter_values(item)
            return cleaned
        if isinstance(value, list):
            return [self._remove_unresolved_parameter_values(item) for item in value if not self._contains_unresolved_workflow_template(item)]
        return value

    def _usable_agent_results(self, agent_results: list[AgentExecutionResult]) -> list[AgentExecutionResult]:
        blocked_statuses = {"requires_key", "requires_input", "paused"}
        placeholder_texts = {
            "The primary runtime paused before producing a user-facing final answer.",
            "The primary runtime completed without a user-facing final answer.",
        }
        usable: list[AgentExecutionResult] = []
        seen: set[str] = set()
        for result in reversed(agent_results):
            key = result.participant_id or result.participant_name
            if key in seen:
                continue
            seen.add(key)
            answer = (result.final_answer or "").strip()
            if result.status in blocked_statuses:
                continue
            if str(result.status or "").lower() != "completed":
                continue
            if answer in placeholder_texts:
                continue
            if not self._answer_has_result_material(answer):
                continue
            usable.append(result)
        return list(reversed(usable))

    async def _compose_or_escalate_delegated_final_answer(
        self,
        *,
        core_run_id: str,
        task_name: str,
        task_instruction: str,
        agent_results: list[AgentExecutionResult],
        shared_context: dict[str, Any],
    ) -> str:
        fallback = self._compose_delegated_final_answer(
            task_name=task_name,
            task_instruction=task_instruction,
            agent_results=agent_results,
        )
        if not agent_results:
            return fallback
        if not bool(shared_context.get("model_escalation_requested")):
            return fallback
        try:
            import json
            payload = {
                "task_name": task_name,
                "task_instruction": task_instruction,
                "feedback": shared_context.get("feedback") if isinstance(shared_context.get("feedback"), dict) else {},
                "participant_results": [
                    {
                        "participant_name": r.participant_name,
                        "status": r.status,
                        "result": self._clean_participant_answer(r.final_answer),
                    }
                    for r in agent_results
                ],
                "instructions": [
                    "Create one clean user-facing final answer.",
                    "Do not include internal routing, trace, or debug text.",
                    "Do not invent facts not present in participant_results.",
                    "If participant output is noisy, extract only clearly supported facts and state uncertainty briefly.",
                    "Return JSON with key final_answer only.",
                ],
            }
            adapter = {
                "adapter_id": "delegated_final_synthesis_escalated",
                "runtime_role": "final_user_response",
                "route_name": "stable_synthesis_strong",
                "model_route_name": "stable_synthesis_strong",
                "preferred_capabilities": ["stable_synthesis", "structured_output", "semantic_compression"],
                "prompt_policy": {"max_context_tokens": 2800},
            }
            prompt = {"id": "delegated_final_synthesis", "system": "Return valid JSON only."}
            schema = {"type": "object", "properties": {"final_answer": {"type": "string"}}, "required": ["final_answer"]}
            result = await self.router.generate_json(
                run_id=core_run_id,
                node_id="output",
                adapter=adapter,
                prompt=prompt,
                rendered_user_prompt=safe_json_dumps(payload),
                schema=schema,
            )
            value = result.get("final_answer") if isinstance(result, dict) else None
            if isinstance(value, str) and value.strip():
                return value.strip()
        except Exception:
            return fallback
        return fallback


    def _answer_has_result_material(self, answer: str) -> bool:
        """Return True only when a participant answer contains user-facing material.

        This guard is intentionally generic. It prevents old fallback paths from
        being treated as successful answers when they only return provenance,
        placeholders, or internal failure text.
        """
        text = str(answer or "").strip()
        if not text:
            return False

        compact = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        lower = compact.lower()

        placeholder_fragments = [
            "completed without a user-facing final answer",
            "paused before producing a user-facing final answer",
            "intermediate node data was intentionally not exposed",
            "could not be completed with verified result material",
            "no completed participant result",
            "no verified result material",
            "could not produce a verified answer",
            "could not produce a verified final answer",
            "could not extract enough structured",
            "evidence is insufficient",
            "insufficient structured evidence",
            "not available in this environment",
            "cannot perform the requested action",
            "cannot perform the requested actions",
            "i cannot perform",
            "unable to perform",
            "source only",
            "classified intent is",
            "initial capability needs",
            "no missing required parameters",
            "agent actions and substeps planned",
            "locked fixed execution options",
            "workflow is blocked and did not execute",
            "please review the blocked step details",
            "workflow initialized",
            "initializing workflow",
            "status: initializing",
            "the workflow is blocked",
            "not json serializable",
            "is not json serializable",
            "object of type",
            "serialization_failure",
            "runtime payload is not serializable",
            "runtime_serialization_problem",
        ]
        if any(fragment in lower for fragment in placeholder_fragments):
            return False

        internal_labels = {
            "input_parsing",
            "intent_recognition",
            "requirement_completion",
            "context_awareness",
            "workflow_planning",
            "agent_action_planning",
            "execution_preparation",
            "pre_execution_validation",
            "execution",
            "result_verification",
            "feedback_repair",
            "final_synthesis",
            "dataflow_step",
            "runtime_error",
            "tool_execution",
        }
        normalized_label = re.sub(r"[^a-z0-9_]+", "_", lower).strip("_")
        if normalized_label in internal_labels:
            return False

        if lower in {"initializing", "pending", "planning", "planning_active", "ready_for_planning", "completed", "failed", "success"}:
            return False

        meaningful_lines = []
        for line in compact.splitlines():
            l = line.strip()
            low = l.lower()
            if not l:
                continue
            if low in {"source:", "sources:", "details:", "summary:", "final answer:", "i found the following:"}:
                continue
            if low.startswith("source:") or low.startswith("sources:"):
                continue
            if low.startswith("- http://") or low.startswith("- https://") or low.startswith("http://") or low.startswith("https://"):
                continue
            meaningful_lines.append(l)

        if not meaningful_lines:
            return False

        # A single label-like line without a value is not enough. Keep this
        # generic by checking for textual or numeric payload, not domain terms.
        joined = " ".join(meaningful_lines).strip()
        alpha_count = sum(1 for ch in joined if ch.isalpha())
        digit_count = sum(1 for ch in joined if ch.isdigit())
        if alpha_count + digit_count < 8:
            return False
        return True


    def _compose_delegated_final_answer(
        self,
        *,
        task_name: str,
        task_instruction: str,
        agent_results: list[AgentExecutionResult],
    ) -> str:
        if not agent_results:
            return "The delegated task failed: no participant result was available for final synthesis."
        successful: list[tuple[str, str]] = []
        failed: list[str] = []
        failure_details: list[str] = []
        for result in agent_results:
            label = result.participant_name or result.participant_id or "participant"
            status = str(result.status or "completed")
            answer = self._clean_participant_answer((result.final_answer or "").strip())
            if status == "completed" and answer:
                successful.append((label, answer))
            else:
                failed.append(label)
                if answer:
                    failure_details.append(f"{label}: {answer}")

        lines: list[str] = []
        if successful:
            if len(successful) == 1:
                lines.append(successful[0][1])
            else:
                for label, answer in successful:
                    lines.append(f"{label}:")
                    lines.append(answer)
                    lines.append("")
        if failed:
            lines.append("Some requested parts could not be completed with verified result material: " + ", ".join(failed) + ".")
            if failure_details:
                lines.append("Failure details:")
                lines.extend(f"- {item}" for item in failure_details)
        answer = "\n".join(line for line in lines if line is not None).strip()
        return answer or "I could not produce a verified final answer for this task."

    def _clean_participant_answer(self, answer: str) -> str:
        text = str(answer or "").strip()
        # Participant output is already generated by the primary runtime. This
        # cleanup removes old fallback trust boilerplate that would make the
        # final delegated answer read like a log instead of a user response.
        marker = "\n\nTrust: unverified generated result."
        if marker in text:
            text = text.split(marker, 1)[0].strip()
        if any(str(m).casefold() in text.casefold() for m in self.INTERNAL_OUTPUT_MARKERS):
            return ""
        return text

    def _build_synthesis_message(
        self,
        task_name: str,
        task_instruction: str,
        agent_results: list[AgentExecutionResult],
        shared_context: dict[str, Any],
    ) -> str:
        result_blocks = []
        for result in agent_results:
            result_blocks.append(
                f"Participant: {result.participant_name}\n"
                f"Status: {result.status}\n"
                f"Result: {result.final_answer}"
            )
        return (
            "Synthesize the delegated participant results into the final answer for the user.\n"
            f"Task name: {task_name}\n"
            f"Task instruction: {task_instruction}\n"
            "Participant results:\n"
            + "\n---\n".join(result_blocks)
            + "\nReturn a concise final answer."
        )


    def _extract_investigation_report_answer(self, results: dict[str, Any]) -> str:
        """Extract a safe user-facing answer from generic runtime results.

        This method is intentionally domain-neutral. It only trusts fields that
        are explicitly answer/result/message fields and ignores node internals,
        schemas, prompts, provider traces, and empty placeholder structures.
        """
        if not isinstance(results, dict):
            return ""

        preferred_nodes = ["output", "final", "synthesis", "execution", "runtime_error"]
        preferred_keys = ["final_answer", "answer", "message", "result", "summary", "content", "text"]

        def clean(value: Any) -> str:
            if value is None:
                return ""
            if isinstance(value, (dict, list)):
                return ""
            text = str(value).strip()
            if not text:
                return ""
            lowered = text.lower()
            if "completed without a user-facing final answer" in lowered:
                return ""
            if "intermediate node data was intentionally not exposed" in lowered:
                return ""
            if any(str(marker).casefold() in text.casefold() for marker in self.INTERNAL_OUTPUT_MARKERS):
                return ""
            return text

        for node_id in preferred_nodes:
            node = results.get(node_id)
            if isinstance(node, dict):
                for key in preferred_keys:
                    text = clean(node.get(key))
                    if text:
                        return text
            else:
                text = clean(node)
                if text:
                    return text

        for node_id, node in results.items():
            if str(node_id) in {"input_parsing", "intent_recognition", "requirement_completion", "context_awareness", "workflow_planning", "agent_action_planning", "execution_preparation", "pre_execution_validation", "result_verification", "feedback_repair", "final_synthesis"}:
                continue
            if isinstance(node, dict):
                status = str(node.get("status") or node.get("execution_status") or "").lower()
                if status in {"failed", "error", "timeout"}:
                    for key in ["message", "error", "detail", "reason"]:
                        text = clean(node.get(key))
                        if text:
                            return text
                for key in preferred_keys:
                    text = clean(node.get(key))
                    if text:
                        return text
            else:
                text = clean(node)
                if text:
                    return text
        return ""

    def _extract_final_answer(self, state: dict[str, Any]) -> str:
        results = state.get("results", {}) if isinstance(state, dict) else {}

        # Public answer extraction must follow the runtime public-output
        # contract, not the physical storage location.  Some callers persist
        # primary-runtime nodes under workflow_results or nested result payloads;
        # if we only inspect results, downstream workflow variables such as
        # {{Step.final_answer}} can receive the generic no-answer placeholder.
        # Keep this generic by scanning known public terminal nodes across all
        # public result containers and rejecting internal/placeholder text.
        result_containers: list[dict[str, Any]] = []
        if isinstance(results, dict):
            result_containers.append(results)
        workflow_results = state.get("workflow_results") if isinstance(state, dict) else None
        if isinstance(workflow_results, dict):
            result_containers.append(workflow_results)
        nested_result = state.get("result") if isinstance(state, dict) else None
        if isinstance(nested_result, dict):
            nested_workflow = nested_result.get("workflow_results")
            if isinstance(nested_workflow, dict):
                result_containers.append(nested_workflow)
            nested_results = nested_result.get("results")
            if isinstance(nested_results, dict):
                result_containers.append(nested_results)

        for container in result_containers:
            for node_id in ("output", "final_synthesis", "final", "synthesis", "conversation_output"):
                node = container.get(node_id) if isinstance(container, dict) else None
                if isinstance(node, dict):
                    for key in ("final_answer", "answer", "answer_material", "result", "content", "text", "message"):
                        value = node.get(key)
                        if isinstance(value, str) and value.strip() and self._answer_has_result_material(value):
                            return value.strip()

        # If the terminal synthesis failed to expose answer material, extract it
        # from public execution contracts.  This is still limited to explicit
        # public answer keys and will not leak internal prompt/contracts.
        for container in result_containers:
            execution = container.get("execution") if isinstance(container, dict) else None
            answer_from_execution = self._extract_public_answer_material(execution)
            if answer_from_execution:
                return answer_from_execution

        for key in ["final_answer", "answer", "result", "message"]:
            value = state.get(key) if isinstance(state, dict) else None
            if isinstance(value, str) and value.strip() and self._answer_has_result_material(value):
                return str(value).strip()
        if isinstance(state, dict) and state.get("error"):
            return str(state.get("error"))
        pending = state.get("pending_action") if isinstance(state, dict) else None
        if pending:
            return ""
        for container in result_containers:
            report_answer = self._extract_investigation_report_answer(container)
            if report_answer and self._answer_has_result_material(report_answer):
                return report_answer
        # No public answer was produced. Return empty so downstream dataflow
        # gates can stop safely instead of treating a placeholder as payload.
        return ""

    def _extract_public_answer_material(self, value: Any) -> str:
        # Only explicit public answer fields are eligible. Generic content/text
        # fields are often prompt-contract bodies and must not leak to delivery.
        public_keys = ("answer_material", "final_answer", "answer", "generated_content")

        def safe_text(text: str) -> str:
            clean = str(text or "").strip()
            if not clean or not self._answer_has_result_material(clean):
                return ""
            if any(str(marker).casefold() in clean.casefold() for marker in self.INTERNAL_OUTPUT_MARKERS):
                return ""
            return clean

        def scan(item: Any) -> str:
            if isinstance(item, dict):
                for key in public_keys:
                    val = item.get(key)
                    if isinstance(val, str):
                        text = safe_text(val)
                        if text:
                            return text
                    if isinstance(val, (dict, list)):
                        nested = scan(val)
                        if nested:
                            return nested
                for key, child in item.items():
                    if str(key) in self.INTERNAL_OUTPUT_KEYS:
                        continue
                    if isinstance(child, (dict, list)):
                        nested = scan(child)
                        if nested:
                            return nested
            elif isinstance(item, list):
                for child in item[:20]:
                    nested = scan(child)
                    if nested:
                        return nested
            return ""
        return scan(value)

    def _extract_status(self, state: dict[str, Any]) -> str:
        if isinstance(state, dict) and str(state.get("status") or "") in {"failed", "completed", "timeout"}:
            return "failed" if str(state.get("status")) == "timeout" else str(state.get("status"))
        pending = state.get("pending_action") if isinstance(state, dict) else None
        if isinstance(pending, dict):
            kind = str(pending.get("kind") or "pending")
            if kind in {"secret_input", "optional_credential_choice"}:
                return "requires_key"
            if kind in {"human_information_required", "collect_runtime_parameters", "runtime_parameter_input", "uploaded_artifact_parameters"}:
                return "requires_input"
            return "paused"
        results = state.get("results", {}) if isinstance(state, dict) else {}
        output = results.get("output") if isinstance(results, dict) else None
        if isinstance(output, dict):
            return str(output.get("status") or output.get("execution_status") or "completed")
        if isinstance(results, dict) and results:
            return "incomplete"
        return "completed"

    def _extract_missing_inputs(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        pending = state.get("pending_action") if isinstance(state, dict) else None
        if not isinstance(pending, dict):
            return []
        kind = str(pending.get("kind") or "")
        if kind == "secret_input":
            request = pending.get("request") if isinstance(pending.get("request"), dict) else {}
            api_source = request.get("api_source") if isinstance(request.get("api_source"), dict) else {}
            api_sources = request.get("api_sources") if isinstance(request.get("api_sources"), list) else []
            secret_fields = request.get("secret_fields") if isinstance(request.get("secret_fields"), list) else []
            first_secret = secret_fields[0] if secret_fields and isinstance(secret_fields[0], dict) else {}
            provider = str(api_source.get("provider") or first_secret.get("provider") or request.get("provider") or pending.get("provider") or "credential-protected provider")
            source_url = str(api_source.get("url") or first_secret.get("source_url") or pending.get("source_url") or "")
            field_name = str(first_secret.get("name") or api_source.get("secret_key") or pending.get("secret_key") or "runtime_access_key")
            return [{
                "kind": "secret_input",
                "field": field_name,
                "message": str(pending.get("message") or request.get("message") or "A credential-protected method is available. Enter the key to use it, or continue without this key to try another allowed method."),
                "input_type": "password",
                "required": False,
                "provider": provider,
                "source_url": source_url,
                "api_source": api_source,
                "api_sources": api_sources,
            }]
        if kind == "optional_credential_choice":
            request = pending.get("request") if isinstance(pending.get("request"), dict) else {}
            api_source = request.get("api_source") if isinstance(request.get("api_source"), dict) else {}
            api_sources = request.get("api_sources") if isinstance(request.get("api_sources"), list) else []
            secret_fields = request.get("secret_fields") if isinstance(request.get("secret_fields"), list) else []
            first_secret = secret_fields[0] if secret_fields and isinstance(secret_fields[0], dict) else {}
            provider = str(api_source.get("provider") or first_secret.get("provider") or request.get("provider") or pending.get("provider") or "credential-protected provider")
            source_url = str(api_source.get("url") or first_secret.get("source_url") or pending.get("source_url") or "")
            field_name = str(first_secret.get("name") or api_source.get("secret_key") or request.get("secret_key") or request.get("provider") or "runtime_access_key")
            return [{
                "kind": "optional_credential_choice",
                "field": field_name,
                "message": str(request.get("message") or pending.get("message") or "A credential-protected method can improve this execution. Enter the key to use it, or continue without this key."),
                "input_type": "password",
                "required": False,
                "provider": provider,
                "source_url": source_url,
                "api_source": api_source,
                "api_sources": api_sources,
            }]
        if kind in {"collect_runtime_parameters", "runtime_parameter_input", "uploaded_artifact_parameters"}:
            request = pending.get("request") if isinstance(pending.get("request"), dict) else {}
            fields = request.get("fields") if isinstance(request.get("fields"), list) else []
            out = []
            for idx, f in enumerate(fields):
                if isinstance(f, dict):
                    field = str(f.get("field") or f.get("name") or f.get("source_field") or f"field_{idx}")
                    out.append({
                        "kind": kind,
                        "field": field,
                        "label": str(f.get("label") or field),
                        "message": str(f.get("question") or f.get("prompt") or f.get("message") or f.get("description") or request.get("message") or "Please provide this runtime value."),
                        "input_type": str(f.get("input_type") or f.get("type") or "text"),
                        "required": f.get("required", True) is not False,
                        "placeholder": str(f.get("placeholder") or f"Enter {field}"),
                        "description": str(f.get("description") or ""),
                        "aliases": f.get("aliases") if isinstance(f.get("aliases"), list) else [],
                        "merge_targets": f.get("merge_targets") if isinstance(f.get("merge_targets"), list) else [],
                    })
                elif isinstance(f, str) and f.strip():
                    out.append({"kind": kind, "field": f.strip(), "label": f.strip(), "message": str(request.get("message") or "Please provide this runtime value."), "input_type": "text", "required": True})
            return out
        if kind == "human_information_required":
            request = pending.get("request") if isinstance(pending.get("request"), dict) else {}
            fields = request.get("fields") or request.get("missing_fields") or []
            if isinstance(fields, list):
                out = []
                for idx, f in enumerate(fields):
                    if isinstance(f, dict):
                        field = str(f.get("field") or f.get("name") or f.get("source_field") or f"field_{idx}")
                        out.append({
                            "kind": "human_information_required",
                            "field": field,
                            "label": str(f.get("label") or field),
                            "message": str(f.get("question") or f.get("prompt") or f.get("message") or f.get("description") or request.get("message") or "Additional information is required."),
                            "input_type": str(f.get("input_type") or f.get("type") or "text"),
                            "placeholder": str(f.get("placeholder") or f"Enter {field}"),
                            "aliases": f.get("aliases") if isinstance(f.get("aliases"), list) else [],
                            "merge_targets": f.get("merge_targets") if isinstance(f.get("merge_targets"), list) else [],
                        })
                    elif isinstance(f, str):
                        out.append({"kind": "human_information_required", "field": str(f), "message": str(request.get("message") or "Additional information is required.")})
                return out
        if kind == "validation_recovery":
            node_id = str(pending.get("node_id") or "")
            result = state.get("results", {}).get(node_id, {}) if isinstance(state.get("results"), dict) else {}
            paths = self._collect_null_paths(result)
            if not paths:
                paths = ["corrected_json"]
            message = "Schema validation failed. Please provide a valid value for the highlighted field."
            validation_error = str(pending.get("validation_error") or "")
            return [{
                "kind": "validation_recovery",
                "field": path,
                "message": message,
                "validation_error": validation_error,
                "node_id": node_id,
            } for path in paths]
        return []
