from __future__ import annotations

from dataclasses import dataclass
import json
import asyncio
from collections.abc import Callable
import uuid
from typing import Any

from ai_core.orchestration.workflow_runtime import WorkflowRuntime
from ai_core.llm.provider_router import ProviderRouter
from ai_core.runtime.governance import RuntimeCostPolicy
from auxiliary_brain.protocols.runtime_protocol import PrimaryRuntimeRequestEnvelope, PrimaryRuntimeExecutionPolicy


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

    def __init__(self, runtime: WorkflowRuntime | None = None) -> None:
        self.runtime = runtime or WorkflowRuntime()
        self.router = ProviderRouter()

    async def execute_agent_request(self, request: AgentExecutionRequest, progress_callback: Callable[[dict[str, Any]], Any] | None = None) -> AgentExecutionResult:
        message = self._build_agent_message(request)
        core_run_id, state = await self.runtime.prepare(message)
        state.setdefault("runtime_options", {})["delegation_mode"] = True
        state.setdefault("runtime_options", {})["auto_approve_reviews"] = True
        if progress_callback:
            self.runtime.add_event_listener(core_run_id, progress_callback)
        try:
            await self._run_runtime_with_timeout(core_run_id, state, self.runtime.run_prepared(state))
        finally:
            if progress_callback:
                self.runtime.remove_event_listener(core_run_id, progress_callback)
        final_answer = self._extract_final_answer(state)
        status = self._extract_status(state)
        pending_action = state.get("pending_action") if isinstance(state, dict) else None
        return AgentExecutionResult(
            participant_id=request.participant_id,
            participant_name=request.participant_name,
            core_run_id=core_run_id,
            status=status,
            final_answer=final_answer,
            workflow_results=state.get("results", {}),
            pending_action=pending_action if isinstance(pending_action, dict) else None,
            missing_inputs=self._extract_missing_inputs(state),
        )


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
        timeout_seconds = max(300, int(getattr(snapshot, "operation_timeout_seconds", 45)) + 120)
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
        final_answer = await self._compose_or_escalate_delegated_final_answer(
            core_run_id=core_run_id,
            task_name=task_name,
            task_instruction=task_instruction,
            agent_results=usable_results,
            shared_context=shared_context or {},
        )
        return {
            "origin": "ai_core",
            "core_run_id": core_run_id,
            "status": "completed" if usable_results else "completed_with_no_participant_result",
            "final_answer": final_answer,
            "workflow_results": {
                "delegated_synthesis": {
                    "status": "completed",
                    "participant_count": len(agent_results),
                    "used_participant_count": len(usable_results),
                    "omitted_participant_count": max(0, len(agent_results) - len(usable_results)),
                }
            },
        }

    def _build_agent_message(self, request: AgentExecutionRequest) -> str:
        import json

        envelope = PrimaryRuntimeRequestEnvelope(
            request_type="agent_execution",
            task_name=request.task_name,
            participant_name=request.participant_name,
            participant_id=request.participant_id,
            objective=(request.participant_instruction or "").strip(),
            task_instruction=request.task_instruction,
            community_id=request.community_id,
            context=request.shared_context or {},
            execution_policy=PrimaryRuntimeExecutionPolicy(),
        )
        return (
            "Execute this canonical auxiliary-to-primary runtime request.\n"
            "The auxiliary layer only controls roles, tasks, context, missing information, and feedback.\n"
            "The primary runtime must perform parsing, intent recognition, workflow planning, capability routing, tool execution, evidence verification, and final answer synthesis.\n"
            "Do not create or redefine participants or tasks. Execute only the objective in the JSON envelope.\n"
            "Return only the participant result needed for the task, as a final user-facing answer.\n"
            "Never return intermediate node JSON as the final answer.\n"
            + json.dumps(envelope.to_prompt_payload(), ensure_ascii=False)
        )

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
                rendered_user_prompt=json.dumps(payload, ensure_ascii=False),
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
            "source only",
        ]
        if any(fragment in lower for fragment in placeholder_fragments):
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
            return "The delegated task completed, but no completed participant result was available for final synthesis."
        successful: list[tuple[str, str]] = []
        failed: list[str] = []
        for result in agent_results:
            label = result.participant_name or result.participant_id or "participant"
            status = str(result.status or "completed")
            answer = self._clean_participant_answer((result.final_answer or "").strip())
            if status == "completed" and answer:
                successful.append((label, answer))
            else:
                failed.append(label)

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

    def _extract_final_answer(self, state: dict[str, Any]) -> str:
        results = state.get("results", {}) if isinstance(state, dict) else {}
        output = results.get("output") if isinstance(results, dict) else None
        if isinstance(output, dict):
            for key in ["final_answer", "message", "answer", "result"]:
                value = output.get(key)
                if value:
                    return str(value)
        for key in ["final_answer", "message", "answer", "result"]:
            value = state.get(key) if isinstance(state, dict) else None
            if value:
                return str(value)
        pending = state.get("pending_action") if isinstance(state, dict) else None
        if pending:
            return "The primary runtime paused before producing a user-facing final answer."
        if isinstance(results, dict) and results:
            report_answer = self._extract_investigation_report_answer(results)
            if report_answer:
                return report_answer
            return "The primary runtime completed without a user-facing final answer. Intermediate node data was intentionally not exposed."
        return "The primary runtime completed without a user-facing final answer."


    def _extract_investigation_report_answer(self, results: dict[str, Any]) -> str:
        """Derive a user-facing answer from completed intermediate results.

        This is intentionally generic: it only looks for common result fields,
        status fields, evidence-like lists, and error material. It does not
        contain business/domain keywords. It prevents delegated execution from
        crashing when the output node did not run but earlier nodes produced
        usable material.
        """
        if not isinstance(results, dict) or not results:
            return ""

        preferred_keys = ["output", "final", "final_result", "synthesis", "execution", "answer"]
        for key in preferred_keys:
            value = results.get(key)
            text = self._coerce_user_text(value)
            if self._answer_has_result_material(text):
                return text

        collected: list[str] = []
        failures: list[str] = []
        for node_id, value in results.items():
            if str(node_id).startswith("runtime_timeout"):
                failures.append(str(value.get("reason") if isinstance(value, dict) else value))
                continue
            status = str(value.get("status") or value.get("execution_status") or "") if isinstance(value, dict) else ""
            text = self._coerce_user_text(value)
            if status.lower() in {"failed", "error", "timeout", "execution_timeout"}:
                if text:
                    failures.append(f"{node_id}: {text}")
                else:
                    failures.append(str(node_id))
                continue
            if self._answer_has_result_material(text):
                collected.append(text)

        if collected:
            return "\n\n".join(collected[:3]).strip()
        if failures:
            return "The runtime could not produce a verified final answer. " + "; ".join(failures[:3])
        return ""

    def _coerce_user_text(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (int, float, bool)):
            return str(value)
        if isinstance(value, list):
            parts = [self._coerce_user_text(item) for item in value]
            return "\n".join(p for p in parts if p).strip()
        if isinstance(value, dict):
            for key in ["final_answer", "message", "answer", "result", "summary", "content", "text", "output"]:
                text = self._coerce_user_text(value.get(key))
                if self._answer_has_result_material(text):
                    return text
            pairs: list[str] = []
            for key, child in value.items():
                if str(key).startswith("_"):
                    continue
                if key in {"raw", "debug", "trace", "metadata", "schema", "input"}:
                    continue
                text = self._coerce_user_text(child)
                if self._answer_has_result_material(text):
                    pairs.append(f"{key}: {text}")
            return "\n".join(pairs[:8]).strip()
        return ""

    def _extract_status(self, state: dict[str, Any]) -> str:
        if isinstance(state, dict) and str(state.get("status") or "") in {"failed", "completed", "timeout"}:
            return "failed" if str(state.get("status")) == "timeout" else str(state.get("status"))
        pending = state.get("pending_action") if isinstance(state, dict) else None
        if isinstance(pending, dict):
            kind = str(pending.get("kind") or "pending")
            if kind in {"secret_input", "optional_credential_choice"}:
                return "requires_key"
            if kind == "human_information_required":
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
        if kind == "human_information_required":
            request = pending.get("request") if isinstance(pending.get("request"), dict) else {}
            fields = request.get("fields") or request.get("missing_fields") or []
            if isinstance(fields, list):
                return [{"kind": "human_information_required", "field": str(f), "message": str(request.get("message") or "Additional information is required.")} for f in fields]
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
