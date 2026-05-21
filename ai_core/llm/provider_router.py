import time
from ai_core.config.loader import ConfigLoader
from ai_core.runtime.modeling.model_provider_autoconfig import ModelProviderAutoConfigurator
from ai_core.config.paths import RUNTIME_CONFIGS
from ai_core.events.event_bus import event_bus
from ai_core.llm.provider_handler_registry import ProviderHandlerRegistry
from ai_core.llm.provider_handlers.base import ProviderUnavailableError
from ai_core.context.prompt_budget_manager import PromptBudgetManager
from ai_core.llm.model_capability_matcher import ModelCapabilityMatcher
from ai_core.runtime.modeling import ModelRoutingPlanner, ModelStagePolicy, RuntimeExecutionPolicy
from ai_core.runtime.governance import RuntimeCostPolicy
from ai_core.secrets.secret_store import SecretStore
from ai_core.runtime.modeling.user_model_selection import UserModelSelectionStore
from ai_core.llm.prompt_io_recorder import PromptIORecorder


class ProviderRouter:
    """
    Generic LLM provider router.

    Provider execution is delegated by provider.type from runtime config.
    """

    def __init__(self) -> None:
        self.loader = ConfigLoader()
        self.registry = ProviderHandlerRegistry()
        self.provider_autoconfig = ModelProviderAutoConfigurator()
        self.prompt_budget = PromptBudgetManager()
        self.model_matcher = ModelCapabilityMatcher()
        self.routing_planner = ModelRoutingPlanner()
        self.stage_policy = ModelStagePolicy()
        self.runtime_execution_policy = RuntimeExecutionPolicy()
        self.runtime_cost_policy = RuntimeCostPolicy()
        self.prompt_io_recorder = PromptIORecorder()


    def _apply_stage_prompt_guard(self, *, node_id: str, adapter: dict) -> dict:
        """Apply generic per-stage LLM budgets before provider routing.

        This is not task/domain logic. It prevents local models from receiving
        large execution traces, candidate pages, or repeated fallback material.
        Heavy evidence should be reduced deterministically before any LLM call.
        """
        updated = dict(adapter or {})
        node = str(node_id or "")
        if node in {"agent_parameter_contract", "input_parsing"}:
            updated["max_prompt_tokens"] = min(int(updated.get("max_prompt_tokens") or 520), 520)
            updated["provider_timeout_seconds"] = min(float(updated.get("provider_timeout_seconds") or 90), 90.0)
            updated["max_schema_chars"] = min(int(updated.get("max_schema_chars") or 900), 900)
            updated.setdefault("provider_options", {})
            updated["provider_options"].update({"temperature": 0, "num_predict": 256, "num_ctx": 1536, "think": False})
        elif node == "intent_recognition":
            updated["max_prompt_tokens"] = min(int(updated.get("max_prompt_tokens") or 800), 800)
            updated["provider_timeout_seconds"] = min(float(updated.get("provider_timeout_seconds") or 60), 60.0)
            updated["max_schema_chars"] = min(int(updated.get("max_schema_chars") or 1500), 1500)
            updated.setdefault("provider_options", {})
            updated["provider_options"].update({"temperature": 0, "num_predict": 384, "num_ctx": 2048, "think": False})
        elif node == "workflow_planning":
            updated["max_prompt_tokens"] = min(int(updated.get("max_prompt_tokens") or 520), 520)
            updated["provider_timeout_seconds"] = min(float(updated.get("provider_timeout_seconds") or 35), 35.0)
            updated["max_schema_chars"] = min(int(updated.get("max_schema_chars") or 900), 900)
            updated["max_provider_attempts"] = 1
            updated.setdefault("provider_options", {})
            updated["provider_options"].update({"temperature": 0, "num_predict": 256, "num_ctx": 1536, "think": False})
        elif node == "execution":
            updated["max_prompt_tokens"] = min(int(updated.get("max_prompt_tokens") or 800), 800)
            updated["provider_timeout_seconds"] = min(float(updated.get("provider_timeout_seconds") or 30), 30.0)
            updated["max_schema_chars"] = min(int(updated.get("max_schema_chars") or 1000), 1000)
            updated["max_provider_attempts"] = 1
            updated.setdefault("provider_options", {})
            updated["provider_options"].update({"temperature": 0, "num_predict": 384, "num_ctx": 2048, "think": False})
        return updated

    def _compact_rendered_prompt(self, *, node_id: str, text: str, adapter: dict) -> str:
        """Shrink LLM prompts without relying on business vocabulary.

        The compactor preserves contract-oriented lines and drops bulky trace /
        evidence blocks. This keeps local models from looping over repeated
        execution material.
        """
        text = str(text or "")
        node = str(node_id or "")
        hard_char_limits = {
            "agent_parameter_contract": 1400,
            "input_parsing": 1400,
            "intent_recognition": 1800,
            "workflow_planning": 1600,
            "execution": 1600,
        }
        limit = int(adapter.get("max_prompt_chars") or hard_char_limits.get(node, 5000))
        if len(text) <= limit:
            return text
        if node != "execution":
            return text[: max(0, limit - 24)] + "\n...[prompt_compacted]"

        keep_markers = (
            "objective", "intent", "parameter", "known", "missing",
            "schema", "contract", "source_level", "execution",
            "required", "capability", "step", "status", "error"
        )
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        kept = []
        for line in lines:
            low = line.casefold()
            if any(marker in low for marker in keep_markers):
                kept.append(line[:500])
            if sum(len(x) for x in kept) > limit:
                break
        if not kept:
            kept = lines[:20]
        compacted = "\n".join(kept)
        if len(compacted) > limit:
            compacted = compacted[: max(0, limit - 24)]
        return compacted + "\n...[execution_prompt_compacted]"

    def _config(self) -> dict:
        self.provider_autoconfig.ensure()
        return self.loader.load_yaml(RUNTIME_CONFIGS / "models" / "providers.yaml")


    def _apply_local_model_switch(self, *, route: list[str], providers: dict, config: dict, stage_policy_meta: dict | None) -> list[str]:
        """Apply the canonical runtime execution switch.

        New code must not read legacy local_model_policy/runtime_switch directly.
        The RuntimeExecutionPolicy object centralizes environment overrides,
        runtime policy JSON, and backward-compatible mirrors.
        """
        snapshot = self.runtime_execution_policy.snapshot(provider_config=config)
        return snapshot.filter_route(route, providers)


    def _apply_stage_provider_overrides(self, *, provider: dict, adapter: dict) -> dict:
        """Apply generic stage-level request controls from runtime adapter.

        This keeps provider lifecycle features intact while allowing JSON stages
        to constrain output length, context, temperature, and thinking mode.
        """
        updated = dict(provider or {})
        if isinstance(adapter.get("provider_options"), dict):
            options = dict(updated.get("options") or {})
            for key, value in adapter["provider_options"].items():
                if key == "think":
                    updated["think"] = bool(value)
                else:
                    options[key] = value
            updated["options"] = options
        if adapter.get("provider_timeout_seconds") is not None:
            try:
                updated["timeout_seconds"] = float(adapter.get("provider_timeout_seconds"))
            except Exception:
                pass
        if adapter.get("max_schema_chars") is not None:
            try:
                updated["max_schema_chars"] = int(adapter.get("max_schema_chars"))
            except Exception:
                pass
        return updated

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
        protocol = str(provider.get("protocol") or "")
        updated = dict(provider)
        if protocol == "openai_compatible" and provider_name in {"vllm", "vllm_coder", "lmstudio", "lmstudio_coder"}:
            provider_model = UserModelSelectionStore().provider_model_for(provider_name, selected)
            if provider_model:
                updated["model"] = provider_model
                updated["logical_model_id"] = selected
            return updated
        if protocol != "ollama_chat":
            return provider
        if not provider_name.startswith("ollama"):
            return provider
        provider_model = UserModelSelectionStore().provider_model_for(provider_name, selected)
        allowed = provider.get("available_local_models") or provider.get("fallback_models") or []
        allowed = [str(x) for x in allowed]
        if provider_model not in allowed and selected not in allowed:
            return provider
        selected_runtime_model = provider_model if provider_model in allowed else selected
        updated["model"] = selected_runtime_model
        fallbacks = [selected_runtime_model] + [m for m in allowed if m != selected_runtime_model]
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
        adapter = self.runtime_cost_policy.apply_adapter_budget(adapter, config)
        adapter = self._apply_stage_prompt_guard(node_id=node_id, adapter=adapter)
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
        route = self.runtime_cost_policy.trim_route(route, source=config, escalated=bool(route_plan.get("escalated")))
        last_error = None
        cost_snapshot = self.runtime_cost_policy.snapshot(config)

        await event_bus.emit(run_id, {
            "type": "LLM_ROUTE_START",
            "title": "LLM route started",
            "message": "route=" + str(route_plan.get("route_name")) + "; stage=" + str((stage_policy_meta or {}).get("stage_id")) + "; complexity=" + str((route_plan.get("complexity") or {}).get("level")) + "; providers=" + ", ".join(route),
            "node_id": node_id,
            "route_name": route_plan.get("route_name"),
            "stage_policy": stage_policy_meta,
            "complexity": route_plan.get("complexity"),
            "escalated": route_plan.get("escalated"),
            "cost_policy": {
                "enabled": cost_snapshot.enabled,
                "max_prompt_tokens": cost_snapshot.max_prompt_tokens,
                "max_provider_attempts": cost_snapshot.max_provider_attempts,
            },
        })

        for provider_name in route:
            provider = dict(providers.get(provider_name, {}) or {})
            provider = self._apply_stage_provider_overrides(provider=provider, adapter=adapter)
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
                rendered_for_provider = self._compact_rendered_prompt(node_id=node_id, text=rendered_user_prompt, adapter=adapter)
                budget = self.prompt_budget.budget_for(provider=provider, adapter=adapter)
                budgeted_prompt = self.prompt_budget.fit_text(rendered_for_provider, budget_tokens=budget)
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
                provider_request_trace = self.prompt_io_recorder.record(
                    run_id=run_id,
                    node_id=node_id,
                    phase=f"provider_request_{provider_name}",
                    payload={
                        "run_id": run_id,
                        "node_id": node_id,
                        "provider": provider_name,
                        "provider_type": provider_type,
                        "model": provider.get("model"),
                        "timeout_seconds": provider.get("timeout_seconds"),
                        "options": provider.get("options"),
                        "think": provider.get("think"),
                        "prompt": {"system": prompt.get("system"), "user": budgeted_prompt.text},
                        "schema": schema,
                        "budget": {
                            "budget_tokens": budget,
                            "estimated_tokens": budgeted_prompt.estimated_tokens,
                            "truncated": budgeted_prompt.truncated,
                        },
                    },
                )
                await event_bus.emit(run_id, {
                    "type": "LLM_PROVIDER_REQUEST_RECORDED",
                    "title": "LLM provider request recorded",
                    "message": provider_request_trace,
                    "node_id": node_id,
                    "provider": provider_name,
                    "trace_path": provider_request_trace,
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
                provider_response_trace = self.prompt_io_recorder.record(
                    run_id=run_id,
                    node_id=node_id,
                    phase=f"provider_response_{provider_name}",
                    payload={
                        "run_id": run_id,
                        "node_id": node_id,
                        "provider": provider_name,
                        "provider_type": provider_type,
                        "model": provider.get("model"),
                        "elapsed_seconds": elapsed,
                        "result": result,
                    },
                )
                await event_bus.emit(run_id, {
                    "type": "LLM_PROVIDER_DONE",
                    "title": "LLM provider completed",
                    "message": f"{provider_name} completed in {elapsed}s",
                    "node_id": node_id,
                    "provider": provider_name,
                    "provider_type": provider_type,
                    "elapsed_seconds": elapsed,
                    "trace_path": provider_response_trace,
                })
                return result

            except Exception as exc:
                elapsed = round(time.monotonic() - started, 2)
                last_error = f"{provider_name}: {exc}"

                provider_error_trace = self.prompt_io_recorder.record(
                    run_id=run_id,
                    node_id=node_id,
                    phase=f"provider_error_{provider_name}",
                    payload={
                        "run_id": run_id,
                        "node_id": node_id,
                        "provider": provider_name,
                        "provider_type": provider_type,
                        "model": provider.get("model"),
                        "elapsed_seconds": elapsed,
                        "error": str(exc),
                    },
                )
                await event_bus.emit(run_id, {
                    "type": "LLM_PROVIDER_ERROR",
                    "title": "LLM provider failed",
                    "message": f"{provider_name} failed after {elapsed}s: {exc}; trace={provider_error_trace}",
                    "node_id": node_id,
                    "provider": provider_name,
                    "provider_type": provider_type,
                    "elapsed_seconds": elapsed,
                    "trace_path": provider_error_trace,
                })

                if "MISSING_SECRET:" in str(exc):
                    secret_key = str(exc).split("MISSING_SECRET:", 1)[1].split()[0].strip() or "provider_secret"
                    # The secret may have been provided by a previous participant
                    # during the same delegation run. Re-check the canonical store
                    # before emitting another UI interaction. This prevents repeated
                    # API-key prompts when resume state is stale or multiple agents
                    # share the same provider credential.
                    if SecretStore().has(secret_key):
                        last_error = f"MISSING_SECRET_ALREADY_SATISFIED:{secret_key}"
                        continue
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
