import asyncio
import httpx
from ai_core.events.event_bus import event_bus
from ai_core.llm.provider_command_runner import ProviderCommandRunner
from ai_core.llm.provider_installer import ProviderInstaller
from ai_core.llm.provider_handlers.base import ProviderUnavailableError
from ai_core.llm.provider_handlers.utils import build_system_prompt, parse_json_content, response_json_or_error


class OllamaProviderHandler:
    provider_type = "ollama"

    def __init__(self) -> None:
        self.command_runner = ProviderCommandRunner()
        self.installer = ProviderInstaller()

    async def generate_json(self, *, run_id: str, node_id: str, provider_name: str, provider: dict, prompt: dict, rendered_user_prompt: str, schema: dict) -> dict:
        binary = await self.installer.ensure_binary(run_id, provider_name, provider)
        provider["_resolved_binary"] = binary

        base = provider.get("base_url", "http://127.0.0.1:11434").rstrip("/")
        primary_model = provider.get("model", "qwen3-vl:8b-thinking")
        timeout = provider.get("timeout_seconds", 120)

        tags = await self._ensure_service(run_id, node_id, provider_name, provider, base)
        selected_model = await self._ensure_model_with_fallbacks(run_id, node_id, provider_name, provider, base, primary_model, tags)

        endpoint_strategy = provider.get("endpoint_strategy", "auto")
        chat_endpoint = provider.get("chat_endpoint", "/api/chat")
        generate_endpoint = provider.get("generate_endpoint", "/api/generate")

        if endpoint_strategy == "chat":
            return await self._call_chat_endpoint(run_id, node_id, provider_name, base, chat_endpoint, selected_model, prompt, rendered_user_prompt, schema, timeout)
        if endpoint_strategy == "generate":
            return await self._call_generate_endpoint(run_id, node_id, provider_name, base, generate_endpoint, selected_model, prompt, rendered_user_prompt, schema, timeout)

        try:
            return await self._call_chat_endpoint(run_id, node_id, provider_name, base, chat_endpoint, selected_model, prompt, rendered_user_prompt, schema, timeout)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
            await event_bus.emit(run_id, {
                "type": "LLM_ENDPOINT_FALLBACK",
                "title": "Ollama endpoint fallback",
                "message": f"{chat_endpoint} returned 404. Falling back to {generate_endpoint}.",
                "node_id": node_id,
                "provider": provider_name,
                "model": selected_model,
            })
            return await self._call_generate_endpoint(run_id, node_id, provider_name, base, generate_endpoint, selected_model, prompt, rendered_user_prompt, schema, timeout)

    def _format_command(self, provider: dict, template: str, **kwargs) -> str:
        command = template.replace("{binary}", provider.get("_resolved_binary") or provider.get("binary", "ollama"))
        for k, v in kwargs.items():
            command = command.replace("{" + k + "}", str(v))
        return command

    async def _call_chat_endpoint(self, run_id, node_id, provider_name, base, endpoint, model, prompt, rendered_user_prompt, schema, timeout):
        payload = {
            "model": model,
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
            "message": f"{provider_name}: POST {endpoint}, waiting for model response...",
            "node_id": node_id,
            "provider": provider_name,
            "model": model,
        })
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(base + endpoint, json=payload)
                response.raise_for_status()
                content = response_json_or_error(response, provider_name=provider_name, endpoint=endpoint).get("message", {}).get("content", "")
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError(
                f"Ollama request timed out. endpoint={endpoint}, model={model}, timeout_seconds={timeout}. "
                "The model may still be loading or inference is too slow. "
                "Try increasing timeout_seconds or using a smaller/faster model."
            ) from exc
        return parse_json_content(content)

    async def _call_generate_endpoint(self, run_id, node_id, provider_name, base, endpoint, model, prompt, rendered_user_prompt, schema, timeout):
        payload = {
            "model": model,
            "stream": False,
            "format": "json",
            "prompt": build_system_prompt(prompt, schema) + "\n\nUser prompt:\n" + rendered_user_prompt,
        }
        await event_bus.emit(run_id, {
            "type": "LLM_REQUEST_SENT",
            "title": "LLM request sent",
            "message": f"{provider_name}: POST {endpoint}, waiting for model response...",
            "node_id": node_id,
            "provider": provider_name,
            "model": model,
        })
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(base + endpoint, json=payload)
                response.raise_for_status()
                content = response_json_or_error(response, provider_name=provider_name, endpoint=endpoint).get("response", "")
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError(
                f"Ollama request timed out. endpoint={endpoint}, model={model}, timeout_seconds={timeout}. "
                "The model may still be loading or inference is too slow. "
                "Try increasing timeout_seconds or using a smaller/faster model."
            ) from exc
        return parse_json_content(content)

    async def _ensure_service(self, run_id: str, node_id: str, provider_name: str, provider: dict, base: str) -> dict:
        tags = await self._try_tags(base)
        if tags is not None:
            await self._emit_health_ok(run_id, node_id, provider_name)
            return tags

        if not provider.get("auto_start", True):
            raise ProviderUnavailableError(f"{provider_name}: service is not reachable and auto_start is disabled.")

        start_template = provider.get("start_command", "{binary} serve")
        start_command = self._format_command(provider, start_template)

        await event_bus.emit(run_id, {
            "type": "LLM_PROVIDER_AUTOSTART",
            "title": "Starting provider service",
            "message": start_command,
            "node_id": node_id,
            "provider": provider_name,
        })

        proc = await asyncio.create_subprocess_shell(
            start_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        await event_bus.emit(run_id, {
            "type": "PROVIDER_DAEMON_STARTED",
            "title": "Provider daemon started",
            "message": f"pid={proc.pid}",
            "node_id": node_id,
            "provider": provider_name,
            "pid": proc.pid,
        })

        timeout = int(provider.get("ready_timeout_seconds", 30))
        interval = float(provider.get("ready_poll_interval_seconds", 1.0))
        attempts = max(1, int(timeout / interval))

        for _ in range(attempts):
            await asyncio.sleep(interval)
            tags = await self._try_tags(base)
            if tags is not None:
                await self._emit_health_ok(run_id, node_id, provider_name)
                return tags

        raise ProviderUnavailableError(f"{provider_name}: service did not become ready. Command: {start_command}")

    async def _try_tags(self, base: str) -> dict | None:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(base + "/api/tags")
                response.raise_for_status()
                return response.json()
        except Exception:
            return None

    async def _emit_health_ok(self, run_id: str, node_id: str, provider_name: str) -> None:
        await event_bus.emit(run_id, {
            "type": "LLM_HEALTH_OK",
            "title": "Provider health OK",
            "message": provider_name,
            "node_id": node_id,
            "provider": provider_name,
        })

    async def _ensure_model_with_fallbacks(self, run_id: str, node_id: str, provider_name: str, provider: dict, base: str, primary_model: str, tags: dict) -> str:
        candidates = [primary_model] + [m for m in provider.get("fallback_models", []) if m and m != primary_model]
        errors = []

        for idx, model in enumerate(candidates):
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
                "type": "LLM_MODEL_MISSING" if idx == 0 else "LLM_MODEL_FALLBACK",
                "title": "Ollama model missing" if idx == 0 else "Trying fallback model",
                "message": f"Model '{model}' was not found. Pulling it now.",
                "node_id": node_id,
                "provider": provider_name,
                "model": model,
            })

            if not provider.get("auto_pull_missing_model", True):
                errors.append(f"{model}: missing and auto pull disabled")
                continue

            command = self._format_command(provider, provider.get("pull_command", "{binary} pull {model}"), model=model)
            result = await self.command_runner.run(
                run_id=run_id,
                title=f"Pull Ollama model {model}",
                command=command,
                timeout_seconds=provider.get("pull_timeout_seconds", 3600),
            )
            if result.returncode != 0:
                error = f"Model pull failed: {model}\n{result.summary()}"
                errors.append(error)
                await event_bus.emit(run_id, {
                    "type": "LLM_MODEL_PULL_FAILED",
                    "title": "Model pull failed",
                    "message": error,
                    "node_id": node_id,
                    "provider": provider_name,
                    "model": model,
                })
                continue

            tags = await self._try_tags(base) or {}
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

            errors.append(f"{model}: pull succeeded but model still not found")

        raise ProviderUnavailableError("All Ollama model pull attempts failed.\n\n" + "\n\n---\n\n".join(errors))

    def _model_exists(self, tags: dict, model: str) -> bool:
        names = set()
        for item in tags.get("models", []):
            name = item.get("name")
            if name:
                names.add(name)
                names.add(name.split(":")[0])
        return model in names or model.split(":")[0] in names
