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

    Each brain requests a model by role/task/complexity.  The router selects the
    model from policy; callers never hard-code concrete model names.  Both async
    and sync methods are provided because verification often runs in normal
    synchronous post-execution hooks.
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

    def complete_sync(
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
        return self.complete_with_route_sync(route=route, messages=messages, response_format=response_format, **kwargs)

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

        errors: list[dict[str, Any]] = []
        for attempt_route in self._route_attempts(route):
            model = self._litellm_model(attempt_route)
            options = self._merge_options(route=attempt_route, response_format=response_format, kwargs=kwargs)
            try:
                raw = await acompletion(model=model, messages=messages, **options)
                route_payload = attempt_route.to_dict()
                if errors:
                    route_payload["previous_attempts"] = errors
                return LiteLLMBrainResult(status="completed", content=self._extract_content(raw), route=route_payload, raw=raw)
            except Exception as exc:
                errors.append({"provider": attempt_route.provider, "model": attempt_route.model, "error": str(exc)[:1000]})
        return LiteLLMBrainResult(status="failed", route=route.to_dict(), error=json_dumps_compact(errors))

    def complete_with_route_sync(
        self,
        *,
        route: BrainModelRoute,
        messages: list[dict[str, str]],
        response_format: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> LiteLLMBrainResult:
        try:
            from litellm import completion
        except Exception as exc:  # pragma: no cover - environment dependent
            return LiteLLMBrainResult(status="litellm_unavailable", route=route.to_dict(), error=str(exc))

        errors: list[dict[str, Any]] = []
        for attempt_route in self._route_attempts(route):
            model = self._litellm_model(attempt_route)
            options = self._merge_options(route=attempt_route, response_format=response_format, kwargs=kwargs)
            try:
                raw = completion(model=model, messages=messages, **options)
                route_payload = attempt_route.to_dict()
                if errors:
                    route_payload["previous_attempts"] = errors
                return LiteLLMBrainResult(status="completed", content=self._extract_content(raw), route=route_payload, raw=raw)
            except Exception as exc:
                errors.append({"provider": attempt_route.provider, "model": attempt_route.model, "error": str(exc)[:1000]})
        return LiteLLMBrainResult(status="failed", route=route.to_dict(), error=json_dumps_compact(errors))

    def _merge_options(self, *, route: BrainModelRoute, response_format: dict[str, Any] | None, kwargs: dict[str, Any]) -> dict[str, Any]:
        options = dict(route.options or {})
        options.update(kwargs)
        if response_format:
            options["response_format"] = response_format
        return options

    def _extract_content(self, raw: Any) -> str:
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
        return content

    def _litellm_model(self, route: BrainModelRoute) -> str:
        provider = str(route.provider or "").strip()
        model = str(route.model or "").strip()
        if not provider:
            return model
        if model.startswith(provider + "/"):
            return model
        return f"{provider}/{model}" if model else provider

    def _route_attempts(self, route: BrainModelRoute) -> list[BrainModelRoute]:
        attempts = [route]
        for item in route.fallback or []:
            if isinstance(item, dict):
                attempts.append(self._fallback_route(base=route, item=item))
        return attempts

    def _fallback_route(self, *, base: BrainModelRoute, item: dict[str, Any]) -> BrainModelRoute:
        return BrainModelRoute(
            brain=base.brain,
            task_type=base.task_type,
            complexity=base.complexity,
            provider=str(item.get("provider") or base.provider),
            model=str(item.get("model") or base.model),
            model_alias=str(item.get("model_alias") or item.get("alias") or base.model_alias),
            source=f"{base.source}:fallback",
            options=item.get("options") if isinstance(item.get("options"), dict) else dict(base.options or {}),
            fallback=[],
            decision_reason=str(item.get("reason") or "fallback_route"),
        )


def json_dumps_compact(value: Any) -> str:
    try:
        import json

        return json.dumps(value, ensure_ascii=False, default=str)[:2000]
    except Exception:
        return str(value)[:2000]
