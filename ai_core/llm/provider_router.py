import time
from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import RUNTIME_CONFIGS
from ai_core.events.event_bus import event_bus
from ai_core.llm.provider_handler_registry import ProviderHandlerRegistry
from ai_core.llm.provider_handlers.base import ProviderUnavailableError
from ai_core.context.prompt_budget_manager import PromptBudgetManager


class ProviderRouter:
    """
    Generic LLM provider router.

    Provider execution is delegated by provider.type from runtime config.
    """

    def __init__(self) -> None:
        self.loader = ConfigLoader()
        self.registry = ProviderHandlerRegistry()
        self.prompt_budget = PromptBudgetManager()

    def _config(self) -> dict:
        return self.loader.load_yaml(RUNTIME_CONFIGS / "models" / "providers.yaml")

    async def generate_json(self, run_id: str, node_id: str, adapter: dict, prompt: dict, rendered_user_prompt: str, schema: dict) -> dict:
        config = self._config()
        route = adapter.get("provider_route") or config.get("default_route", [])
        providers = config.get("providers", {})
        last_error = None

        await event_bus.emit(run_id, {
            "type": "LLM_ROUTE_START",
            "title": "LLM route started",
            "message": "Trying providers: " + ", ".join(route),
            "node_id": node_id,
        })

        for provider_name in route:
            provider = providers.get(provider_name, {})
            if not provider.get("enabled", False):
                await event_bus.emit(run_id, {
                    "type": "LLM_PROVIDER_SKIPPED",
                    "title": "Provider skipped",
                    "message": f"{provider_name} is disabled or missing.",
                    "node_id": node_id,
                    "provider": provider_name,
                })
                continue

            provider_type = provider.get("type")
            started = time.monotonic()

            await event_bus.emit(run_id, {
                "type": "LLM_PROVIDER_START",
                "title": "Calling LLM provider",
                "message": f"{provider_name} / type={provider_type} / model={provider.get('model')}",
                "node_id": node_id,
                "provider": provider_name,
                "provider_type": provider_type,
                "model": provider.get("model"),
            })

            try:
                handler = self.registry.get(provider_type)
                budget = self.prompt_budget.budget_for(provider=provider, adapter=adapter)
                budgeted_prompt = self.prompt_budget.fit_text(rendered_user_prompt, budget_tokens=budget)
                if budgeted_prompt.truncated:
                    await event_bus.emit(run_id, {
                        "type": "LLM_PROMPT_BUDGET_APPLIED",
                        "title": "Prompt budget applied",
                        "message": f"Prompt reduced to fit budget. estimated_tokens={budgeted_prompt.estimated_tokens}, budget_tokens={budget}",
                        "node_id": node_id,
                        "provider": provider_name,
                        "model": provider.get("model"),
                        "estimated_tokens": budgeted_prompt.estimated_tokens,
                        "budget_tokens": budget,
                    })
                result = await handler.generate_json(
                    run_id=run_id,
                    node_id=node_id,
                    provider_name=provider_name,
                    provider=provider,
                    prompt=prompt,
                    rendered_user_prompt=budgeted_prompt.text,
                    schema=schema,
                )

                elapsed = round(time.monotonic() - started, 2)
                await event_bus.emit(run_id, {
                    "type": "LLM_PROVIDER_DONE",
                    "title": "LLM provider completed",
                    "message": f"{provider_name} completed in {elapsed}s",
                    "node_id": node_id,
                    "provider": provider_name,
                    "provider_type": provider_type,
                    "elapsed_seconds": elapsed,
                })
                return result

            except Exception as exc:
                elapsed = round(time.monotonic() - started, 2)
                last_error = f"{provider_name}: {exc}"

                await event_bus.emit(run_id, {
                    "type": "LLM_PROVIDER_ERROR",
                    "title": "LLM provider failed",
                    "message": f"{provider_name} failed after {elapsed}s: {exc}",
                    "node_id": node_id,
                    "provider": provider_name,
                    "provider_type": provider_type,
                    "elapsed_seconds": elapsed,
                })

                if "MISSING_SECRET:" in str(exc):
                    raise

        raise ProviderUnavailableError(
            "No real LLM provider is available. "
            "Check runtime/configs/models/providers.yaml. "
            "Last error: " + str(last_error)
        )
