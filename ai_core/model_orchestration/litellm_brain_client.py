from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ai_core.model_orchestration.brain_model_router import BrainModelRoute, BrainModelRouter


@dataclass
class LiteLLMBrainResult:
    status: str
    content: str = ""
    route: dict[str, Any] = field(default_factory=dict)
    raw: Any = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LiteLLMBrainClient:
    """LiteLLM client facade used by all separated brains.

    The client receives brain/task/complexity, asks BrainModelRouter for a
    policy-selected model, then calls LiteLLM.  Code that uses this client never
    hard-codes concrete model names.
    """

    def __init__(self, *, router: BrainModelRouter | None = None) -> None:
        self.router = router or BrainModelRouter()

    async def complete(
        self,
        *,
        brain: str,
        task_type: str = "default",
        complexity: str = "default",
        messages: list[dict[str, str]],
        context: dict[str, Any] | None = None,
        response_format: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> LiteLLMBrainResult:
        route = self.router.select(brain=brain, task_type=task_type, complexity=complexity, context=context or {})
        return await self.complete_with_route(route=route, messages=messages, response_format=response_format, **kwargs)

    async def complete_with_route(
        self,
        *,
        route: BrainModelRoute,
        messages: list[dict[str, str]],
        response_format: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> LiteLLMBrainResult:
        try:
            from litellm import acompletion
        except Exception as exc:  # pragma: no cover - environment dependent
            return LiteLLMBrainResult(status="litellm_unavailable", route=route.to_dict(), error=str(exc))

        model = self._litellm_model(route)
        options = dict(route.options or {})
        options.update(kwargs)
        if response_format:
            options["response_format"] = response_format
        try:
            raw = await acompletion(model=model, messages=messages, **options)
            content = ""
            choices = getattr(raw, "choices", None) or []
            if choices:
                message = getattr(choices[0], "message", None)
                content = getattr(message, "content", "") if message is not None else ""
                if isinstance(message, dict):
                    content = str(message.get("content") or content)
            if not content and isinstance(raw, dict):
                try:
                    content = str(raw["choices"][0]["message"].get("content") or "")
                except Exception:
                    content = ""
            return LiteLLMBrainResult(status="completed", content=content, route=route.to_dict(), raw=raw)
        except Exception as exc:
            return LiteLLMBrainResult(status="failed", route=route.to_dict(), error=str(exc))

    def _litellm_model(self, route: BrainModelRoute) -> str:
        provider = str(route.provider or "").strip()
        model = str(route.model or "").strip()
        if not provider:
            return model
        if model.startswith(provider + "/"):
            return model
        return f"{provider}/{model}" if model else provider
