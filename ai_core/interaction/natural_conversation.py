from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import asyncio

from ai_core.knowledge.knowledge_service import KnowledgeService
from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import CONFIGS_DIR, RUNTIME_CONFIGS
from ai_core.llm.provider_router import ProviderRouter
from ai_core.llm.provider_handlers.base import ProviderUnavailableError
from ai_core.runtime.modeling.user_model_selection import UserModelSelectionStore
from ai_core.interaction.conversation_core_runtime import ConversationCoreRuntime
from ai_core.media import ImageGenerationService


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
        self.image_generation = ImageGenerationService()
        self.config_loader = ConfigLoader()

    async def reply(self, message: str, *, latest_task: str | None = None, session_id: str | None = None) -> dict[str, Any]:
        text = str(message or "").strip()
        if not text:
            answer = "Please enter the content you want me to handle."
            return self._payload(answer, latest_task=latest_task, intent="empty_message")

        modality_route = self._detect_output_modality(text)
        if modality_route:
            routed = await self._handle_modality_request(text, modality_route, latest_task=latest_task)
            if routed:
                return routed

        # Direct conversation is intentionally outside task/graph execution.
        # It may use a small model for user-facing wording, but it must not
        # create workflow graphs or run the full cognitive pipeline.
        answer = await self._model_answer(text)
        if not answer:
            answer = self._safe_fallback_answer(text)
        return self._payload(answer, latest_task=latest_task, intent="general_chat", knowledge_used=False)


    def _detect_output_modality(self, text: str) -> dict[str, Any]:
        policy = self._output_modality_policy()
        tokens = set(self._semantic_tokens(text))
        best: dict[str, Any] = {}
        best_score = 0.0
        for route in policy.get("routes", []) if isinstance(policy.get("routes"), list) else []:
            if not isinstance(route, dict):
                continue
            for token_set in route.get("match_any_token_sets", []) or []:
                required = {str(item).casefold().strip() for item in token_set if str(item).strip()}
                if required and required.issubset(tokens):
                    score = float(route.get("confidence") or 0.0) + (len(required) / 100.0)
                    if score > best_score:
                        best_score = score
                        best = dict(route)
                    break
        return best

    def _output_modality_policy(self) -> dict[str, Any]:
        for path in (RUNTIME_CONFIGS / "interaction" / "output_modality_routing.json", CONFIGS_DIR / "output_modality_routing.seed.json"):
            data = self.config_loader.load_json(path)
            if isinstance(data, dict) and data:
                return data
        return {"routes": []}

    def _semantic_tokens(self, text: str) -> list[str]:
        import re

        return re.findall(r"[a-z0-9_]+", str(text or "").casefold())

    async def _handle_modality_request(self, text: str, route: dict[str, Any], *, latest_task: str | None) -> dict[str, Any]:
        capability_type = str(route.get("capability_type") or "").strip()
        output_modality = str(route.get("output_modality") or "").strip()
        if capability_type == "image_generation":
            payload = await self.image_generation.generate(prompt=text, options={"requested_output_modality": output_modality})
            if payload.get("ok"):
                material = payload.get("material") if isinstance(payload.get("material"), dict) else {}
                url = str(material.get("download_url") or "").strip()
                name = str(material.get("file_name") or output_modality or "generated_material").strip()
                answer = f"Generated {output_modality}: ![{name}]({url})\nDownload: [{name}]({url})" if url else f"Generated {output_modality} material is available."
                result = self._payload(answer, latest_task=latest_task, intent="modality_generation", knowledge_used=False)
                result.update({"output_modality": output_modality, "capability_type": capability_type, "material": material})
                return result
            answer = str(payload.get("message") or "The requested output modality is recognized, but no configured provider produced material.").strip()
            result = self._payload(answer, latest_task=latest_task, intent="modality_generation_setup", knowledge_used=False)
            result.update({"status": str(payload.get("status") or "requires_setup"), "output_modality": output_modality, "capability_type": capability_type, "provider_result": payload})
            return result
        if capability_type:
            answer = "The requested output modality is recognized, but no configured provider is available for it yet."
            result = self._payload(answer, latest_task=latest_task, intent="modality_generation_setup", knowledge_used=False)
            result.update({"status": "requires_setup", "output_modality": output_modality, "capability_type": capability_type})
            return result
        return {}

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
        # user-facing, avoid exposing runtime internals, and do not rely on
        # hard-coded conversational phrase lists.
        if not text.strip():
            return "Please enter the content you want me to handle."
        return (
            "I am your AI runtime assistant. I can help with conversation, explanation, "
            "writing, planning, code-related work, and runtime tasks when you explicitly ask for them."
        )
