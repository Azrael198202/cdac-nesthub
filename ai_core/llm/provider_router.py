import time
from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import RUNTIME_CONFIGS
from ai_core.events.event_bus import event_bus
from ai_core.llm.provider_handler_registry import ProviderHandlerRegistry
from ai_core.llm.provider_handlers.base import ProviderUnavailableError
from ai_core.context.prompt_budget_manager import PromptBudgetManager
from ai_core.llm.model_capability_matcher import ModelCapabilityMatcher
from ai_core.runtime.modeling import ModelRoutingPlanner, ModelStagePolicy, RuntimeExecutionPolicy


class ProviderRouter:
    """
    Generic LLM provider router.

    Provider execution is delegated by provider.type from runtime config.
    """

    def __init__(self) -> None:
        self.loader = ConfigLoader()
        self.registry = ProviderHandlerRegistry()
        self.prompt_budget = PromptBudgetManager()
        self.model_matcher = ModelCapabilityMatcher()
        self.routing_planner = ModelRoutingPlanner()
        self.stage_policy = ModelStagePolicy()
        self.runtime_execution_policy = RuntimeExecutionPolicy()

    def _config(self) -> dict:
        return self.loader.load_yaml(RUNTIME_CONFIGS / "models" / "providers.yaml")


    def _apply_local_model_switch(self, *, route: list[str], providers: dict, config: dict, stage_policy_meta: dict | None) -> list[str]:
        """Apply the canonical runtime execution switch.

        New code must not read legacy local_model_policy/runtime_switch directly.
        The RuntimeExecutionPolicy object centralizes environment overrides,
        runtime policy JSON, and backward-compatible mirrors.
        """
        snapshot = self.runtime_execution_policy.snapshot(provider_config=config)
        return snapshot.filter_route(route, providers)

    def _provider_is_local(self, *, provider_name: str, provider: dict) -> bool:
        return self.runtime_execution_policy.snapshot().provider_is_local(provider_name, provider)

    def _apply_runtime_model_override(self, *, provider_name: str, provider: dict, adapter: dict) -> dict:
        """Apply user-selected local model to generic local providers only.

        This keeps code-generation routes free to select coder-specialized models,
        while allowing the UI to choose the initial/general local model used by
        parsing, intent, planning, retrieval, and synthesis tasks.
        """
        selected = str(adapter.get("preferred_local_model") or "").strip()
        if not selected:
            return provider
        if provider.get("protocol") != "ollama_chat":
            return provider
        if provider_name != "ollama":
            return provider
        allowed = provider.get("available_local_models") or provider.get("fallback_models") or []
        allowed = [str(x) for x in allowed]
        if selected not in allowed:
            return provider
        updated = dict(provider)
        updated["model"] = selected
        fallbacks = [selected] + [m for m in allowed if m != selected]
        updated["fallback_models"] = fallbacks
        if "vl" in selected or "vision" in selected:
            tags = set(updated.get("model_tags") or []) | {"vision", "screenshot_analysis", "ui_understanding"}
            caps = set(updated.get("capabilities") or []) | {"vision", "screenshot_analysis", "ui_understanding"}
        else:
            tags = set(updated.get("model_tags") or []) - {"vision", "screenshot_analysis", "ui_understanding"}
            caps = set(updated.get("capabilities") or []) - {"vision", "screenshot_analysis", "ui_understanding"}
        updated["model_tags"] = sorted(tags)
        updated["capabilities"] = sorted(caps)
        return updated

    async def generate_json(self, run_id: str, node_id: str, adapter: dict, prompt: dict, rendered_user_prompt: str, schema: dict) -> dict:
        config = self._config()
        route = list(adapter.get("provider_route") or config.get("default_route", []))
        providers = config.get("providers", {})
        route_plan = self.routing_planner.plan(
            node_id=node_id,
            adapter=adapter,
            prompt=prompt,
            rendered_user_prompt=rendered_user_prompt,
            schema=schema,
            provider_config=config,
            default_route=route,
        )
        route = route_plan.get("route") or route
        config, route, stage_policy_meta = self.stage_policy.apply_to_route(
            config=config,
            route=route,
            node_id=node_id,
            adapter=adapter,
            route_name=route_plan.get("route_name"),
            escalated=bool(route_plan.get("escalated")),
        )
        providers = config.get("providers", {})
        route = self._apply_local_model_switch(route=route, providers=providers, config=config, stage_policy_meta=stage_policy_meta)
        route = self.model_matcher.rank_route(route=route, providers=providers, config=config, adapter=adapter)
        last_error = None

        await event_bus.emit(run_id, {
            "type": "LLM_ROUTE_START",
            "title": "LLM route started",
            "message": "route=" + str(route_plan.get("route_name")) + "; stage=" + str((stage_policy_meta or {}).get("stage_id")) + "; complexity=" + str((route_plan.get("complexity") or {}).get("level")) + "; providers=" + ", ".join(route),
            "node_id": node_id,
            "route_name": route_plan.get("route_name"),
            "stage_policy": stage_policy_meta,
            "complexity": route_plan.get("complexity"),
            "escalated": route_plan.get("escalated"),
        })

        for provider_name in route:
            provider = dict(providers.get(provider_name, {}) or {})
            provider = self._apply_runtime_model_override(provider_name=provider_name, provider=provider, adapter=adapter)
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
                    secret_key = str(exc).split("MISSING_SECRET:", 1)[1].split()[0].strip() or "provider_secret"
                    await self._emit_missing_secret_interaction(
                        run_id=run_id,
                        node_id=node_id,
                        provider_name=provider_name,
                        secret_key=secret_key,
                    )
                    last_error = f"MISSING_SECRET:{secret_key}"
                    continue

        raise ProviderUnavailableError(
            "No real LLM provider is available. "
            "Check runtime/configs/models/providers.yaml. "
            "Last error: " + str(last_error)
        )

    async def _emit_missing_secret_interaction(self, *, run_id: str, node_id: str, provider_name: str, secret_key: str) -> None:
        await event_bus.emit(run_id, {
            "type": "INTERACTION_REQUEST",
            "title": "Provider credential required",
            "message": "A provider requires a credential. You can provide it or continue without this provider.",
            "node_id": node_id,
            "workflow_state": "waiting_optional_credential_choice",
            "interaction_type": "optional_credential_choice",
            "provider": provider_name,
            "secret_key": secret_key,
            "secret_fields": [
                {
                    "name": "credential",
                    "label": "Provider API Key",
                    "secret_key": secret_key,
                    "interaction_type": "secret",
                    "required": False,
                    "placeholder": "Paste API key here",
                }
            ],
            "actions": [
                {"id": "continue_without_key", "label": "Continue without API key"},
                {"id": "provide_credential", "label": "Provide API key"},
            ],
        })
