import json
import os
import re
import time
import httpx

from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import RUNTIME_CONFIGS
from ai_core.events.event_bus import event_bus
from ai_core.llm.provider_command_runner import ProviderCommandRunner
from ai_core.secrets.secret_store import SecretStore


class ProviderUnavailableError(RuntimeError):
    pass


class ProviderRouter:
    """
    Generic LLM provider router.

    It only knows provider API protocols.
    Prompts, schemas, adapters, and node behavior are runtime-generated config.
    """

    def __init__(self) -> None:
        self.loader = ConfigLoader()
        self.command_runner = ProviderCommandRunner()
        self.secret_store = SecretStore()

    def _config(self) -> dict:
        return self.loader.load_yaml(RUNTIME_CONFIGS / "models" / "providers.yaml")

    async def generate_json(
        self,
        run_id: str,
        node_id: str,
        adapter: dict,
        prompt: dict,
        rendered_user_prompt: str,
        schema: dict,
    ) -> dict:
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

        for name in route:
            provider = providers.get(name, {})
            if not provider.get("enabled", False):
                await event_bus.emit(run_id, {
                    "type": "LLM_PROVIDER_SKIPPED",
                    "title": "Provider skipped",
                    "message": f"{name} is disabled or missing.",
                    "node_id": node_id,
                    "provider": name,
                })
                continue

            started = time.monotonic()
            await event_bus.emit(run_id, {
                "type": "LLM_PROVIDER_START",
                "title": "Calling LLM provider",
                "message": f"{name} / model={provider.get('model')}",
                "node_id": node_id,
                "provider": name,
                "model": provider.get("model"),
            })

            try:
                if provider.get("type") == "ollama":
                    result = await self._ollama(run_id, node_id, name, provider, prompt, rendered_user_prompt, schema)
                elif provider.get("type") == "openai":
                    result = await self._openai(run_id, node_id, name, provider, prompt, rendered_user_prompt, schema)
                else:
                    raise ProviderUnavailableError(f"Unsupported provider type: {provider.get('type')}")

                elapsed = round(time.monotonic() - started, 2)
                await event_bus.emit(run_id, {
                    "type": "LLM_PROVIDER_DONE",
                    "title": "LLM provider completed",
                    "message": f"{name} completed in {elapsed}s",
                    "node_id": node_id,
                    "provider": name,
                    "elapsed_seconds": elapsed,
                })
                return result

            except Exception as exc:
                elapsed = round(time.monotonic() - started, 2)
                last_error = f"{name}: {exc}"
                await event_bus.emit(run_id, {
                    "type": "LLM_PROVIDER_ERROR",
                    "title": "LLM provider failed",
                    "message": f"{name} failed after {elapsed}s: {exc}",
                    "node_id": node_id,
                    "provider": name,
                    "elapsed_seconds": elapsed,
                })

                if "MISSING_SECRET:" in str(exc):
                    raise

        raise ProviderUnavailableError(
            "No real LLM provider is available. Start Ollama or set OPENAI_API_KEY. "
            "Config file: runtime/configs/models/providers.yaml. Last error: " + str(last_error)
        )

    async def _ollama(self, run_id: str, node_id: str, provider_name: str, provider: dict, prompt: dict, rendered_user_prompt: str, schema: dict) -> dict:
        base = provider.get("base_url", "http://127.0.0.1:11434").rstrip("/")
        model = provider.get("model", "qwen3:4b")
        timeout = provider.get("timeout_seconds", 120)

        await event_bus.emit(run_id, {
            "type": "LLM_HEALTH_CHECK",
            "title": "Checking provider health",
            "message": f"{provider_name}: GET {base}/api/tags",
            "node_id": node_id,
            "provider": provider_name,
        })

        try:
            async with httpx.AsyncClient(timeout=5) as client:
                health = await client.get(base + "/api/tags")
                health.raise_for_status()
                tags = health.json()
        except Exception as exc:
            if provider.get("auto_start", True):
                await event_bus.emit(run_id, {
                    "type": "LLM_PROVIDER_AUTOSTART",
                    "title": "Starting provider service",
                    "message": provider.get("start_command", "ollama serve"),
                    "node_id": node_id,
                    "provider": provider_name,
                })
                start_command = provider.get("start_command", "ollama serve")
                await self.command_runner.run(
                    run_id=run_id,
                    title=f"Start provider {provider_name}",
                    command=start_command,
                    timeout_seconds=provider.get("start_timeout_seconds", 8),
                )
                async with httpx.AsyncClient(timeout=5) as client:
                    health = await client.get(base + "/api/tags")
                    health.raise_for_status()
                    tags = health.json()
            else:
                raise exc

        await event_bus.emit(run_id, {
            "type": "LLM_HEALTH_OK",
            "title": "Provider health OK",
            "message": provider_name,
            "node_id": node_id,
            "provider": provider_name,
        })

        if not self._ollama_model_exists(tags, model):
            await event_bus.emit(run_id, {
                "type": "LLM_MODEL_MISSING",
                "title": "Ollama model missing",
                "message": f"Model '{model}' was not found. Pulling it now.",
                "node_id": node_id,
                "provider": provider_name,
                "model": model,
            })

            if not provider.get("auto_pull_missing_model", True):
                raise ProviderUnavailableError(f"Ollama model missing and auto pull disabled: {model}")

            pull_command = provider.get("pull_command", "ollama pull {model}").replace("{model}", model)
            code = await self.command_runner.run(
                run_id=run_id,
                title=f"Pull Ollama model {model}",
                command=pull_command,
                timeout_seconds=provider.get("pull_timeout_seconds", 3600),
            )
            if code != 0:
                raise ProviderUnavailableError(f"Ollama model pull failed: {model}, returncode={code}")

            async with httpx.AsyncClient(timeout=5) as client:
                health = await client.get(base + "/api/tags")
                health.raise_for_status()
                tags = health.json()

            if not self._ollama_model_exists(tags, model):
                raise ProviderUnavailableError(f"Ollama model still missing after pull: {model}")

            await event_bus.emit(run_id, {
                "type": "LLM_MODEL_READY",
                "title": "Ollama model ready",
                "message": model,
                "node_id": node_id,
                "provider": provider_name,
                "model": model,
            })

        payload = {
            "model": model,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": self._system(prompt, schema)},
                {"role": "user", "content": rendered_user_prompt}
            ]
        }

        await event_bus.emit(run_id, {
            "type": "LLM_REQUEST_SENT",
            "title": "LLM request sent",
            "message": f"{provider_name}: waiting for model response...",
            "node_id": node_id,
            "provider": provider_name,
            "model": model,
            "timeout_seconds": timeout,
        })

        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(base + "/api/chat", json=payload)
            r.raise_for_status()
            content = r.json().get("message", {}).get("content", "")

        await event_bus.emit(run_id, {
            "type": "LLM_RESPONSE_RECEIVED",
            "title": "LLM response received",
            "message": f"{provider_name}: parsing JSON response...",
            "node_id": node_id,
            "provider": provider_name,
        })

        return self._parse_json(content)

    async def _openai(self, run_id: str, node_id: str, provider_name: str, provider: dict, prompt: dict, rendered_user_prompt: str, schema: dict) -> dict:
        key_name = provider.get("api_key_env", "OPENAI_API_KEY")
        key = self.secret_store.get(key_name)
        if not key:
            raise ProviderUnavailableError(f"MISSING_SECRET:{key_name}")

        model = provider.get("model", "gpt-4o-mini")
        timeout = provider.get("timeout_seconds", 120)
        payload = {
            "model": model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": self._system(prompt, schema)},
                {"role": "user", "content": rendered_user_prompt}
            ]
        }
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

        await event_bus.emit(run_id, {
            "type": "LLM_REQUEST_SENT",
            "title": "LLM request sent",
            "message": f"{provider_name}: waiting for model response...",
            "node_id": node_id,
            "provider": provider_name,
            "model": model,
            "timeout_seconds": timeout,
        })

        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]

        await event_bus.emit(run_id, {
            "type": "LLM_RESPONSE_RECEIVED",
            "title": "LLM response received",
            "message": f"{provider_name}: parsing JSON response...",
            "node_id": node_id,
            "provider": provider_name,
        })

        return self._parse_json(content)

    def _ollama_model_exists(self, tags: dict, model: str) -> bool:
        models = tags.get("models", [])
        names = set()
        for item in models:
            name = item.get("name")
            if name:
                names.add(name)
                names.add(name.split(":")[0])
        return model in names or model.split(":")[0] in names

    def _system(self, prompt: dict, schema: dict) -> str:
        return (
            str(prompt.get("system", "")) +
            "\\n\\nReturn exactly one valid JSON object. No markdown. No explanation." +
            "\\nJSON Schema:\\n" +
            json.dumps(schema, ensure_ascii=False, indent=2)
        )

    def _parse_json(self, content: str) -> dict:
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?", "", content).strip()
            content = re.sub(r"```$", "", content).strip()
        return json.loads(content)
