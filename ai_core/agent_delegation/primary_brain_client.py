from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
import uuid
from typing import Any

from ai_core.orchestration.workflow_runtime import WorkflowRuntime


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

    async def execute_agent_request(self, request: AgentExecutionRequest, progress_callback: Callable[[dict[str, Any]], Any] | None = None) -> AgentExecutionResult:
        message = self._build_agent_message(request)
        core_run_id, state = await self.runtime.prepare(message)
        state.setdefault("runtime_options", {})["delegation_mode"] = True
        state.setdefault("runtime_options", {})["auto_approve_reviews"] = True
        if progress_callback:
            self.runtime.add_event_listener(core_run_id, progress_callback)
        try:
            await self.runtime.run_prepared(state)
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


    async def resume_agent_request(self, result_payload: dict[str, Any], progress_callback: Callable[[dict[str, Any]], Any] | None = None) -> AgentExecutionResult:
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
                await self._resume_state_direct(core_run_id, state, pending)
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


    async def _resume_state_direct(self, core_run_id: str, state: dict[str, Any], pending: dict[str, Any]) -> None:
        """Continue a saved primary-runtime state without restarting earlier nodes."""
        kind = str(pending.get("kind") or "")
        retry_index = pending.get("retry_node_index")
        node_id = pending.get("node_id")

        if kind in {"secret_input", "optional_credential_choice"}:
            modified = self._build_resume_modified_result(pending)
            secret_key = str(modified.get("secret_key") or "runtime_access_key")
            secret_value = str(modified.get("value") or modified.get("credential") or modified.get("api_key") or "")
            if not secret_value:
                return
            state.setdefault("runtime_credentials", {})[secret_key] = "***"
            state.setdefault("runtime_execution_preferences", {})["credential_mode"] = "provided"

        if node_id:
            state.get("results", {}).pop(node_id, None)
        if retry_index is not None:
            state["node_index"] = int(retry_index)
        state.pop("pending_action", None)
        self.runtime.checkpoints.save(core_run_id, state)
        await self.runtime._emit(core_run_id, {
            "type": "DURABLE_RESUME_STARTED",
            "title": "Durable resume started",
            "message": "Continuing from the saved primary-runtime checkpoint instead of restarting the workflow.",
            "node_id": node_id,
            "progress": state.get("progress", 0),
            "origin": "ai_core",
        })
        await self.runtime._continue(state)

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
        final_answer = self._compose_delegated_final_answer(
            task_name=task_name,
            task_instruction=task_instruction,
            agent_results=usable_results,
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
        objective = (request.participant_instruction or "").strip()
        return (
            "Execute the delegated participant work using the primary runtime.\n"
            "Use runtime-native observations when the objective can be satisfied by current runtime state; otherwise use verified external or generated capabilities as needed.\n"
            "Return only facts that can be represented as verified runtime facts.\n"
            f"Participant name: {request.participant_name}\n"
            f"Participant work objective: {objective}\n"
            f"Task name: {request.task_name}\n"
            "Do not create or redefine participants or tasks. Execute only the participant work objective.\n"
            "Return only the participant result needed for this task."
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
            usable.append(result)
        return list(reversed(usable))

    def _compose_delegated_final_answer(
        self,
        *,
        task_name: str,
        task_instruction: str,
        agent_results: list[AgentExecutionResult],
    ) -> str:
        if not agent_results:
            return "The delegated task completed, but no completed participant result was available for final synthesis."
        lines = ["Final Answer", "", f"Task: {task_name}"]
        for result in agent_results:
            label = result.participant_name or result.participant_id or "participant"
            status = result.status or "completed"
            answer = self._clean_participant_answer((result.final_answer or "").strip())
            if not answer:
                answer = "No user-facing answer was produced."
            lines.extend(["", f"{label} ({status})", answer])
        return "\n".join(lines).strip()

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
            return str(results)
        return "The primary runtime completed without a user-facing final answer."

    def _extract_status(self, state: dict[str, Any]) -> str:
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
        return "completed"

    def _extract_missing_inputs(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        pending = state.get("pending_action") if isinstance(state, dict) else None
        if not isinstance(pending, dict):
            return []
        kind = str(pending.get("kind") or "")
        if kind == "secret_input":
            return [{
                "kind": "secret_input",
                "field": str(pending.get("secret_key") or "runtime_access_key"),
                "message": "A runtime access key is required to continue this delegated execution.",
            }]
        if kind == "optional_credential_choice":
            request = pending.get("request") if isinstance(pending.get("request"), dict) else {}
            return [{
                "kind": "optional_credential_choice",
                "field": str(request.get("secret_key") or request.get("provider") or "runtime_access_key"),
                "message": str(request.get("message") or pending.get("message") or "A runtime access key can improve this execution."),
            }]
        if kind == "human_information_required":
            request = pending.get("request") if isinstance(pending.get("request"), dict) else {}
            fields = request.get("fields") or request.get("missing_fields") or []
            if isinstance(fields, list):
                return [{"kind": "human_information_required", "field": str(f), "message": str(request.get("message") or "Additional information is required.")} for f in fields]
        return []
