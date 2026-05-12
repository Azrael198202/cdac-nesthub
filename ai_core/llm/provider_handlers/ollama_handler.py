import httpx
from ai_core.events.event_bus import event_bus
from ai_core.llm.provider_command_runner import ProviderCommandRunner
from ai_core.llm.provider_handlers.base import ProviderUnavailableError
from ai_core.llm.provider_handlers.utils import build_system_prompt, parse_json_content


class OllamaProviderHandler:
    provider_type = "ollama"

    def __init__(self) -> None:
        self.command_runner = ProviderCommandRunner()

    async def generate_json(self, *, run_id: str, node_id: str, provider_name: str, provider: dict, prompt: dict, rendered_user_prompt: str, schema: dict) -> dict:
        base = provider.get("base_url", "http://127.0.0.1:11434").rstrip("/")
        primary_model = provider.get("model", "qwen3:4b")
        timeout = provider.get("timeout_seconds", 120)

        tags = await self._ensure_service(run_id, node_id, provider_name, provider, base)
        selected_model = await self._ensure_model_with_fallbacks(run_id, node_id, provider_name, provider, base, primary_model, tags)

        payload = {
            "model": selected_model,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": build_system_prompt(prompt, schema)},
                {"role": "user", "content": rendered_user_prompt},
            ],
        }

        await event_bus.emit(run_id, {
            "type": "LLM_REQUEST_SENT",
            "title": "LLM request sent",
            "message": f"{provider_name}: waiting for model response...",
            "node_id": node_id,
            "provider": provider_name,
            "model": selected_model,
            "timeout_seconds": timeout,
        })

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(base + "/api/chat", json=payload)
            response.raise_for_status()
            content = response.json().get("message", {}).get("content", "")

        await event_bus.emit(run_id, {
            "type": "LLM_RESPONSE_RECEIVED",
            "title": "LLM response received",
            "message": f"{provider_name}: parsing JSON response...",
            "node_id": node_id,
            "provider": provider_name,
            "model": selected_model,
        })

        return parse_json_content(content)

    async def _ensure_service(self, run_id: str, node_id: str, provider_name: str, provider: dict, base: str) -> dict:
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
            if not provider.get("auto_start", True):
                raise exc

            start_command = provider.get("start_command", "ollama serve")
            await event_bus.emit(run_id, {
                "type": "LLM_PROVIDER_AUTOSTART",
                "title": "Starting provider service",
                "message": start_command,
                "node_id": node_id,
                "provider": provider_name,
            })

            command_result = await self.command_runner.run(
                run_id=run_id,
                title=f"Start provider {provider_name}",
                command=start_command,
                timeout_seconds=provider.get("start_timeout_seconds", 8),
            )

            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    health = await client.get(base + "/api/tags")
                    health.raise_for_status()
                    tags = health.json()
            except Exception as retry_exc:
                raise ProviderUnavailableError(
                    "Ollama service is not reachable after auto-start.\n"
                    f"Initial error: {exc}\n"
                    f"Retry error: {retry_exc}\n"
                    f"Auto-start output:\n{command_result.summary()}"
                )

        await event_bus.emit(run_id, {
            "type": "LLM_HEALTH_OK",
            "title": "Provider health OK",
            "message": provider_name,
            "node_id": node_id,
            "provider": provider_name,
        })
        return tags

    async def _ensure_model_with_fallbacks(self, run_id: str, node_id: str, provider_name: str, provider: dict, base: str, primary_model: str, tags: dict) -> str:
        fallback_models = provider.get("fallback_models", [])
        candidate_models = [primary_model] + [m for m in fallback_models if m and m != primary_model]
        pull_errors = []

        for index, model in enumerate(candidate_models):
            if self._model_exists(tags, model):
                await event_bus.emit(run_id, {
                    "type": "LLM_MODEL_READY",
                    "title": "Ollama model ready",
                    "message": model,
                    "node_id": node_id,
                    "provider": provider_name,
                    "model": model,
                })
                return model

            await event_bus.emit(run_id, {
                "type": "LLM_MODEL_MISSING" if index == 0 else "LLM_MODEL_FALLBACK",
                "title": "Ollama model missing" if index == 0 else "Trying fallback model",
                "message": f"Model '{model}' was not found. Pulling it now.",
                "node_id": node_id,
                "provider": provider_name,
                "model": model,
            })

            if not provider.get("auto_pull_missing_model", True):
                pull_errors.append(f"{model}: missing and auto pull disabled")
                continue

            pull_command = provider.get("pull_command", "ollama pull {model}").replace("{model}", model)
            result = await self.command_runner.run(
                run_id=run_id,
                title=f"Pull Ollama model {model}",
                command=pull_command,
                timeout_seconds=provider.get("pull_timeout_seconds", 3600),
            )

            if result.returncode != 0:
                error_text = f"Model pull failed: {model}\n{result.summary()}"
                pull_errors.append(error_text)
                await event_bus.emit(run_id, {
                    "type": "LLM_MODEL_PULL_FAILED",
                    "title": "Model pull failed",
                    "message": error_text,
                    "node_id": node_id,
                    "provider": provider_name,
                    "model": model,
                })
                continue

            async with httpx.AsyncClient(timeout=5) as client:
                health = await client.get(base + "/api/tags")
                health.raise_for_status()
                tags = health.json()

            if self._model_exists(tags, model):
                await event_bus.emit(run_id, {
                    "type": "LLM_MODEL_READY",
                    "title": "Ollama model ready",
                    "message": model,
                    "node_id": node_id,
                    "provider": provider_name,
                    "model": model,
                })
                return model

            pull_errors.append(f"{model}: pull succeeded but model still not found in /api/tags")

        raise ProviderUnavailableError("All Ollama model pull attempts failed.\n\n" + "\n\n---\n\n".join(pull_errors))

    def _model_exists(self, tags: dict, model: str) -> bool:
        names = set()
        for item in tags.get("models", []):
            name = item.get("name")
            if name:
                names.add(name)
                names.add(name.split(":")[0])
        return model in names or model.split(":")[0] in names
