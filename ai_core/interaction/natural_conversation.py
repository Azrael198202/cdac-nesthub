from __future__ import annotations

from typing import Any

from ai_core.knowledge.knowledge_service import KnowledgeService


class NaturalConversationService:
    """Small deterministic natural-conversation layer for the studio shell.

    This is intentionally separate from task execution.  If a message is not a
    management command, the user should still receive a normal conversational
    answer instead of operational guidance.  The service first checks verified
    local knowledge and then falls back to a concise conversational response.
    """

    def __init__(self) -> None:
        self.knowledge = KnowledgeService()

    async def reply(self, message: str, *, latest_task: str | None = None) -> dict[str, Any]:
        text = str(message or "").strip()
        kb = self.knowledge.answer_from_knowledge(text) if text else None
        if kb:
            return {
                "action": "conversation_message",
                "origin": "auxiliary_brain",
                "status": "completed",
                "message": kb.get("answer"),
                "conversation_intent": "knowledge_answer",
                "knowledge_used": True,
                "knowledge_status": self.knowledge.status(),
                "latest_task": latest_task,
            }
        return {
            "action": "conversation_message",
            "origin": "auxiliary_brain",
            "status": "completed",
            "message": self._fallback_message(text),
            "conversation_intent": "general_chat",
            "knowledge_used": False,
            "knowledge_status": self.knowledge.status(),
            "latest_task": latest_task,
        }

    def _fallback_message(self, text: str) -> str:
        if not text:
            return "可以。你可以直接和我交流，也可以让我创建智能体、创建任务或执行任务。"
        if text.endswith("?") or text.endswith("？"):
            return "我可以直接回答这类普通问题；如果需要使用已有知识库，我会优先查询已验证的本地知识。"
        return "明白。我会把这条消息作为普通交流处理；只有明确要求创建智能体、创建任务或执行任务时，才进入任务运行流程。"
