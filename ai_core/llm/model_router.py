from __future__ import annotations
from typing import AsyncGenerator

from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import RUNTIME_CONFIGS_DIR
from ai_core.environment.environment_manager import EnvironmentManager
from ai_core.llm.provider_clients import LLMProviderClient
from ai_core.security.approval_service import ApprovalService
from ai_core.utils.events import StreamEvent


class ModelRouter:
    def __init__(self, approval: ApprovalService):
        self.loader = ConfigLoader()
        self.approval = approval
        self.env = EnvironmentManager(approval)
        self.client = LLMProviderClient()

    def _routes(self) -> dict:
        return self.loader.read(RUNTIME_CONFIGS_DIR / "models" / "routes.yaml", default={}) or {}

    def _providers(self) -> dict:
        cfg = self.loader.read(RUNTIME_CONFIGS_DIR / "environment" / "providers.yaml", default={}) or {}
        return cfg.get("providers", {})

    async def generate(self, task_type: str, prompt: str) -> AsyncGenerator[StreamEvent, None]:
        routes = self._routes()
        provider_order = routes.get("tasks", {}).get(task_type) or routes.get("default_route", [])
        providers = self._providers()
        if not provider_order:
            yield StreamEvent("error", "No model route", f"No provider route configured for {task_type}")
            return

        for provider_name in provider_order:
            provider_cfg = providers.get(provider_name, {})
            yield StreamEvent("model_route", "Trying provider", provider_name, {"task_type": task_type})
            provider_ready = False
            blocked_by_review = False
            async for ev in self.env.ensure_provider(provider_name):
                yield ev
                if ev.type == "provider_ready":
                    provider_ready = True
                if ev.type == "human_review":
                    blocked_by_review = True
                    break
            if blocked_by_review:
                return
            if not provider_ready:
                continue

            result = await self.client.generate(provider_name, prompt, provider_cfg)
            if result.get("ok"):
                yield StreamEvent("model_output", "Model output", result.get("text", ""), result)
                return
            yield StreamEvent("model_error", "Model failed", provider_name, result)

        yield StreamEvent("error", "All providers failed", "No configured provider could complete the request.")
