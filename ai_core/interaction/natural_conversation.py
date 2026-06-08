from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import asyncio

from ai_core.knowledge.knowledge_service import KnowledgeService
from ai_core.llm.provider_router import ProviderRouter
from ai_core.llm.provider_handlers.base import ProviderUnavailableError
from ai_core.runtime.modeling.user_model_selection import UserModelSelectionStore
from ai_core.interaction.conversation_core_runtime import ConversationCoreRuntime


class NaturalConversationService:
    """Natural conversation path for Agent Studio.

    This layer is intentionally outside participant/task execution.  It handles
    ordinary user messages with knowledge lookup first and model-backed chat
    second.  It returns a user-facing answer, not internal runtime JSON.
    """

    def __init__(self) -> None:
        self.knowledge = KnowledgeService()
        self.router = ProviderRouter()
        self.model_selection = UserModelSelectionStore()
        self.core_runtime = ConversationCoreRuntime()

    def needs_core_conversation_pipeline(self, message: str) -> bool:
        """Return whether this message should bypass feedback routing and enter
        the generic conversation pipeline.

        This protects capability-gap and source-backed requests from being
        misclassified as feedback merely because they contain negative wording
        such as "does not have" or "missing".  The decision remains
        domain-neutral and delegates the actual signal detection to
        ConversationCoreRuntime.
        """
        try:
            return bool(self.core_runtime._generic_external_signal(message))
        except Exception:
            return False

    async def reply(self, message: str, *, latest_task: str | None = None, session_id: str | None = None, runtime_state_run_id: str | None = None) -> dict[str, Any]:
        text = str(message or "").strip()
        if not text:
            answer = "Please enter the content you want me to handle."
            return self._payload(answer, latest_task=latest_task, intent="empty_message")

        # Agent Studio conversation now uses the generic ai_core conversation
        # pipeline so external-information requests can pass through
        # input_parsing -> intent_recognition -> context_awareness ->
        # workflow_planning -> execution -> result_verification ->
        # final_synthesis.  This remains domain-neutral: ai_core decides only
        # capability/source policy, not business-specific behavior.
        result = await self.core_runtime.run(text, latest_task=latest_task, session_id=session_id, runtime_state_run_id=runtime_state_run_id)
        if isinstance(result, dict) and (result.get("final_answer") or result.get("message")):
            return result
        answer = self._safe_fallback_answer(text)
        return self._payload(answer, latest_task=latest_task, intent="general_chat", knowledge_used=False)

    def _payload(self, answer: str, *, latest_task: str | None, intent: str, knowledge_used: bool = False) -> dict[str, Any]:
        return {
            "action": "conversation_message",
            "origin": "auxiliary_brain",
            "status": "completed",
            "message": answer,
            "final_answer": answer,
            "conversation_intent": intent,
            "knowledge_used": knowledge_used,
            "knowledge_status": self.knowledge.status(),
            "latest_task": latest_task,
            "user_facing": True,
        }

    async def _model_answer(self, text: str) -> str:
        schema = {
            "type": "object",
            "required": ["answer"],
            "properties": {
                "answer": {"type": "string"},
                "needs_task_runtime": {"type": "boolean"},
                "notes": {"type": "string"},
            },
            "additionalProperties": True,
        }
        prompt = {
            "id": "agent_studio_conversation_response",
            "system": (
                "You are a helpful conversational assistant inside a runtime studio. "
                "Answer the user's ordinary message directly. Do not expose internal JSON, runtime state, "
                "task routing, participants, traces, or implementation details. If the user asks for writing, "
                "planning, explanation, translation, or general advice, provide the requested content directly. "
                "Return only valid JSON matching the schema."
            ),
            "runtime_rules": [
                "Do not create or execute tasks unless the user explicitly asks for runtime task execution.",
                "Do not mention internal routing decisions in the answer.",
                "Use the user's language when it is clear; otherwise answer naturally.",
            ],
        }
        rendered = "User message:\n" + text
        adapter = self.model_selection.initial_adapter_overrides({
            "adapter_id": "agent_studio_conversation_adapter",
            "route_name": "stable_synthesis",
            "model_route_name": "stable_synthesis",
            "provider_route": [],
            "max_prompt_tokens": 600,
            "provider_timeout_seconds": 45,
            "max_provider_attempts": 1,
            "accept_raw_text_as_final_answer": True,
            "json_repair_retry": False,
            "provider_options": {"temperature": 0, "num_predict": 120, "num_ctx": 1024, "think": False},
        })
        run_id = "conversation_" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        try:
            result = await asyncio.wait_for(
                self.router.generate_json(
                    run_id=run_id,
                    node_id="conversation_response",
                    adapter=adapter,
                    prompt=prompt,
                    rendered_user_prompt=rendered,
                    schema=schema,
                ),
                timeout=50,
            )
        except Exception:
            return ""
        answer = str((result or {}).get("answer") or (result or {}).get("final_answer") or "").strip()
        return answer

    def _safe_fallback_answer(self, text: str) -> str:
        # Minimal generic fallback when no model provider is available.  Keep it
        # user-facing, avoid exposing runtime internals, and do not rely on
        # hard-coded conversational phrase lists.
        if not text.strip():
            return "Please enter the content you want me to handle."
        return (
            "I am your AI runtime assistant. I can help with conversation, explanation, "
            "writing, planning, code-related work, and runtime tasks when you explicitly ask for them."
        )
