from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import os
import platform
import shlex
from typing import Any

import httpx

from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import RUNTIME_CONFIGS
from ai_core.secrets.secret_store import SecretStore
from ai_core.runtime.modeling.user_model_selection import UserModelSelectionStore
from ai_core.runtime.modeling.model_provider_autoconfig import ModelProviderAutoConfigurator


@dataclass
class ProviderHealth:
    provider: str
    model_id: str
    family: str
    ok: bool
    reason: str
    requires_secret: str | None = None
    checked_url: str | None = None


class ModelRuntimePreflight:
    """Checks whether the user-selected model mode can actually start.

    This layer is intentionally domain-neutral. It only validates model-provider
    availability and credential readiness before a request enters the runtime
    pipeline. It does not inspect the user task domain or encode task keywords.
    """

    def __init__(self) -> None:
        self.selection_store = UserModelSelectionStore()
        self.loader = ConfigLoader()
        self.secret_store = SecretStore()
        self.provider_autoconfig = ModelProviderAutoConfigurator()

    async def check_before_runtime(self) -> dict[str, Any]:
        self.provider_autoconfig.ensure()
        state = self.selection_store.state()
        selection = state.get("selection") if isinstance(state.get("selection"), dict) else {}
        mode = str(selection.get("mode") or "api_only")
        initial_model_id = str(selection.get("initial_model_id") or "").strip()
        initial_provider = str(selection.get("initial_provider") or "").strip()
        required_secret = state.get("required_secret")

        if mode == "api_only":
            if required_secret and not self.secret_store.has(str(required_secret)):
                return self._requires_secret(selection, str(required_secret))
            health = await self._check_api_provider(initial_provider, initial_model_id)
            if not health.ok:
                return self._blocked(selection, [health], "Selected API provider is not ready.")
            return self._ok(selection, [health])

        if mode == "local_only":
            checks = await self._check_local_provider_chain(initial_model_id, preferred_provider=initial_provider)
            if not any(item.ok for item in checks):
                return self._blocked(
                    selection,
                    checks,
                    "No local model provider is available. Start vLLM/Ollama, install the selected model, or switch to API/Hybrid mode.",
                )
            return self._ok(selection, checks)

        # Hybrid: at least one selected route must be usable. Prefer checking the
        # selected initial model first, then the companion provider family.
        checks: list[ProviderHealth] = []
        initial_family = self.selection_store.family_for_model(initial_model_id) if initial_model_id else "api"
        if initial_family == "local":
            checks.extend(await self._check_local_provider_chain(initial_model_id, preferred_provider=initial_provider))
            api_model = str(selection.get("selected_api_model_id") or "").strip()
            api_provider = self.selection_store.provider_for_model(api_model) if api_model else "openai"
            api_secret = self.selection_store.required_secret_for_model(api_model) if api_model else "OPENAI_API_KEY"
            if api_secret and not self.secret_store.has(api_secret):
                checks.append(ProviderHealth(api_provider, api_model, "api", False, f"Missing secret: {api_secret}", api_secret))
            else:
                checks.append(await self._check_api_provider(api_provider, api_model))
        else:
            if required_secret and not self.secret_store.has(str(required_secret)):
                checks.append(ProviderHealth(initial_provider, initial_model_id, "api", False, f"Missing secret: {required_secret}", str(required_secret)))
            else:
                checks.append(await self._check_api_provider(initial_provider, initial_model_id))
            local_model = str(selection.get("selected_local_model_id") or "qwen3.5:2b-instruct").strip()
            local_provider = self.selection_store.provider_for_model(local_model)
            checks.extend(await self._check_local_provider_chain(local_model, preferred_provider=local_provider))

        if any(item.ok for item in checks):
            return self._ok(selection, checks)
        # In hybrid mode, if the initial API model only lacks a key, ask for it;
        # otherwise return an availability error with all checked providers.
        missing = next((item for item in checks if item.requires_secret), None)
        if missing:
            return self._requires_secret(selection, missing.requires_secret, checks)
        return self._blocked(selection, checks, "No selected model provider is available for the current mode.")

    async def _check_local_provider_chain(self, model_id: str, *, preferred_provider: str | None = None) -> list[ProviderHealth]:
        order = []
        if preferred_provider:
            order.append(str(preferred_provider))
        try:
            policy = self.selection_store._load_policy().get("global_policy", {}).get("runtime_execution_policy", {})
            configured = policy.get("local_provider_order") if isinstance(policy, dict) else None
            if isinstance(configured, list):
                order.extend(str(x) for x in configured if str(x))
        except Exception:
            pass
        # vLLM is optional and is skipped by default on Windows and unless explicitly enabled.
        if os.environ.get("AI_CORE_ENABLE_VLLM", "").strip().lower() in {"1", "true", "yes", "on"} and platform.system().lower() != "windows":
            order.append("vllm")
        order.append("ollama")
        seen = set()
        checks: list[ProviderHealth] = []
        for provider_name in order:
            if provider_name in seen:
                continue
            seen.add(provider_name)
            provider_model = self.selection_store.provider_model_for(provider_name, model_id)
            checks.append(await self._check_local_provider(provider_name, provider_model, logical_model_id=model_id))
            if checks[-1].ok:
                break
        return checks

    async def _check_local_provider(self, provider_name: str, model_id: str, logical_model_id: str | None = None) -> ProviderHealth:
        provider = self._provider_config(provider_name)
        if not provider:
            self.provider_autoconfig.ensure()
            provider = self._provider_config(provider_name)
        if not provider:
            return ProviderHealth(provider_name or "local", model_id, "local", False, "Provider is not configured after runtime auto-configuration.")
        if not provider.get("enabled", True):
            return ProviderHealth(provider_name, model_id, "local", False, "Provider is disabled in configuration.")
        protocol = str(provider.get("protocol") or provider.get("type") or "").lower()
        base_url = str(provider.get("base_url") or "").rstrip("/")
        if not base_url:
            return ProviderHealth(provider_name, model_id, "local", False, "Provider has no base_url configured.")
        try:
            async with httpx.AsyncClient(timeout=2.5) as client:
                if "ollama" in protocol or provider_name == "ollama":
                    url = base_url + "/api/tags"
                    res = await client.get(url)
                    if res.status_code >= 400:
                        return ProviderHealth(provider_name, model_id, "local", False, f"Health check failed: HTTP {res.status_code}", checked_url=url)
                    models = []
                    try:
                        payload = res.json()
                        models = [str(x.get("name") or "") for x in payload.get("models", []) if isinstance(x, dict)]
                    except Exception:
                        models = []
                    if model_id and models and not any(m == model_id or m.startswith(model_id + ":") for m in models):
                        return ProviderHealth(provider_name, model_id, "local", False, f"Provider is running, but selected model is not available: {model_id}", checked_url=url)
                    return ProviderHealth(provider_name, model_id, "local", True, "Provider is reachable.", checked_url=url)
                url = base_url + "/v1/models"
                res = await client.get(url)
                if res.status_code >= 400:
                    # Some local OpenAI-compatible servers do not expose /v1/models.
                    root = await client.get(base_url)
                    if root.status_code >= 500:
                        return ProviderHealth(provider_name, model_id, "local", False, f"Health check failed: HTTP {res.status_code}", checked_url=url)
                    return ProviderHealth(provider_name, model_id, "local", True, "Provider is reachable; served model list is not exposed.", checked_url=url)
                try:
                    payload = res.json()
                    items = payload.get("data", []) if isinstance(payload, dict) else []
                    served = [str(x.get("id") or "") for x in items if isinstance(x, dict)]
                    if model_id and served and model_id not in served:
                        return ProviderHealth(provider_name, model_id, "local", False, f"Provider is reachable, but selected provider model is not being served: {model_id}", checked_url=url)
                except Exception:
                    pass
                return ProviderHealth(provider_name, model_id, "local", True, "Provider is reachable.", checked_url=url)
        except Exception as exc:
            missing_module = self._missing_python_module_for_command(str(provider.get("start_command") or ""))
            if missing_module:
                return ProviderHealth(
                    provider_name or "local",
                    model_id,
                    "local",
                    False,
                    f"Provider auto-start command requires missing Python module: {missing_module}",
                    checked_url=base_url,
                )
            if provider.get("auto_start") or provider.get("auto_install"):
                return ProviderHealth(provider_name or "local", model_id, "local", True, f"Provider is configured for runtime auto-prepare; current health check was not reachable yet: {exc}", checked_url=base_url)
            return ProviderHealth(provider_name or "local", model_id, "local", False, f"Provider is not reachable: {exc}", checked_url=base_url)

    def _missing_python_module_for_command(self, command: str) -> str | None:
        if not command:
            return None
        try:
            parts = shlex.split(command)
        except ValueError:
            return None
        for idx, part in enumerate(parts[:-1]):
            if part == "-m":
                module = parts[idx + 1]
                root = module.split(".", 1)[0]
                if root and importlib.util.find_spec(root) is None:
                    return root
        return None

    async def _check_api_provider(self, provider_name: str, model_id: str) -> ProviderHealth:
        provider = self._provider_config(provider_name)
        if not provider:
            self.provider_autoconfig.ensure()
            provider = self._provider_config(provider_name)
        if not provider:
            return ProviderHealth(provider_name or "api", model_id, "api", False, "Provider is not configured after runtime auto-configuration.")
        if not provider.get("enabled", True):
            return ProviderHealth(provider_name, model_id, "api", False, "Provider is disabled in configuration.")
        secret = self.selection_store.required_secret_for_model(model_id) or provider.get("auth_env") or provider.get("required_secret")
        if secret and not self.secret_store.has(str(secret)):
            return ProviderHealth(provider_name, model_id, "api", False, f"Missing secret: {secret}", str(secret))
        # Avoid a paid test request. A configured API provider with required
        # credentials present is considered ready; actual provider errors will be
        # captured by the normal route trace.
        return ProviderHealth(provider_name or "api", model_id, "api", True, "Provider is configured and required credentials are available.", str(secret) if secret else None)

    def _provider_config(self, provider_name: str) -> dict[str, Any]:
        try:
            config = self.loader.load_yaml(RUNTIME_CONFIGS / "models" / "providers.yaml") or {}
            providers = config.get("providers") if isinstance(config.get("providers"), dict) else {}
            provider = providers.get(provider_name) if provider_name else None
            return provider if isinstance(provider, dict) else {}
        except Exception:
            return {}

    def _ok(self, selection: dict[str, Any], checks: list[ProviderHealth]) -> dict[str, Any]:
        return {
            "ok": True,
            "status": "ready",
            "selection": selection,
            "checks": [item.__dict__ for item in checks],
        }

    def _blocked(self, selection: dict[str, Any], checks: list[ProviderHealth], message: str) -> dict[str, Any]:
        return {
            "ok": False,
            "action": "model_preflight",
            "origin": "auxiliary_brain",
            "status": "blocked",
            "message": message,
            "final_answer": message + "\n" + self._format_checks(checks),
            "selection": selection,
            "checks": [item.__dict__ for item in checks],
        }

    def _requires_secret(self, selection: dict[str, Any], secret_key: str, checks: list[ProviderHealth] | None = None) -> dict[str, Any]:
        provider = str(selection.get("initial_provider") or "api provider")
        return {
            "ok": False,
            "action": "model_preflight",
            "origin": "auxiliary_brain",
            "status": "requires_key",
            "message": f"The selected model provider requires {secret_key} before execution can start.",
            "final_answer": f"The selected model provider requires {secret_key} before execution can start.",
            "pending_action": {
                "kind": "secret_input",
                "provider": provider,
                "secret_key": secret_key,
                "message": f"Enter {secret_key} to continue with the selected model provider.",
            },
            "missing_inputs": [
                {
                    "kind": "secret_input",
                    "field": secret_key,
                    "message": f"Enter {secret_key} to continue with the selected model provider.",
                    "input_type": "password",
                    "required": True,
                    "provider": provider,
                }
            ],
            "selection": selection,
            "checks": [item.__dict__ for item in (checks or [])],
        }

    def _format_checks(self, checks: list[ProviderHealth]) -> str:
        if not checks:
            return ""
        lines = ["Provider checks:"]
        for item in checks:
            state = "OK" if item.ok else "NG"
            label = item.provider or item.family
            model = f" / {item.model_id}" if item.model_id else ""
            lines.append(f"- {state}: {label}{model}: {item.reason}")
        return "\n".join(lines)
