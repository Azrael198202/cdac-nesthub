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

    async def reply(self, message: str, *, latest_task: str | None = None, session_id: str | None = None) -> dict[str, Any]:
        text = str(message or "").strip()
        if not text:
            answer = "可以。请直接输入问题、说明、写作要求，或使用明确指令创建智能体、创建任务、执行任务。"
            return self._payload(answer, latest_task=latest_task, intent="empty_message")

        # Direct conversation is intentionally outside task/graph execution.
        # It may use a small model for user-facing wording, but it must not
        # create workflow graphs or run the full cognitive pipeline.
        answer = await self._model_answer(text)
        if not answer:
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
            "provider_timeout_seconds": 18,
            "max_provider_attempts": 1,
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
                timeout=18,
            )
        except Exception:
            return ""
        answer = str((result or {}).get("answer") or "").strip()
        return answer

    def _safe_fallback_answer(self, text: str) -> str:
        # Minimal generic fallback when no model provider is available.  Keep it
        # user-facing and avoid exposing runtime internals.
        if text.endswith("?") or text.endswith("？"):
            return "可以回答。当前模型服务暂时不可用，请稍后重试，或切换到可用的本地/API模型后再次发送。"
        return "收到。当前模型服务暂时不可用，因此无法生成完整内容。请切换到可用模型后再次发送。"
