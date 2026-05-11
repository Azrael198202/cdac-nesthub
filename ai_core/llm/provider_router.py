import json
import os
import re
import httpx

from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import RUNTIME_CONFIGS


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

    def _config(self) -> dict:
        return self.loader.load_yaml(RUNTIME_CONFIGS / "models" / "providers.yaml")

    async def generate_json(self, adapter: dict, prompt: dict, rendered_user_prompt: str, schema: dict) -> dict:
        config = self._config()
        route = adapter.get("provider_route") or config.get("default_route", [])
        providers = config.get("providers", {})
        last_error = None

        for name in route:
            provider = providers.get(name, {})
            if not provider.get("enabled", False):
                continue
            try:
                if provider.get("type") == "ollama":
                    return await self._ollama(provider, prompt, rendered_user_prompt, schema)
                if provider.get("type") == "openai":
                    return await self._openai(provider, prompt, rendered_user_prompt, schema)
            except Exception as exc:
                last_error = f"{name}: {exc}"

        raise ProviderUnavailableError(
            "No real LLM provider is available. Start Ollama or set OPENAI_API_KEY. "
            "Config file: runtime/configs/models/providers.yaml. Last error: " + str(last_error)
        )

    async def _ollama(self, provider: dict, prompt: dict, rendered_user_prompt: str, schema: dict) -> dict:
        base = provider.get("base_url", "http://127.0.0.1:11434").rstrip("/")
        model = provider.get("model", "qwen3:4b")
        timeout = provider.get("timeout_seconds", 120)
        payload = {
            "model": model,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": self._system(prompt, schema)},
                {"role": "user", "content": rendered_user_prompt}
            ]
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(base + "/api/chat", json=payload)
            r.raise_for_status()
            content = r.json().get("message", {}).get("content", "")
            return self._parse_json(content)

    async def _openai(self, provider: dict, prompt: dict, rendered_user_prompt: str, schema: dict) -> dict:
        key = os.getenv(provider.get("api_key_env", "OPENAI_API_KEY"))
        if not key:
            raise ProviderUnavailableError("Missing OPENAI_API_KEY")
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
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            return self._parse_json(content)

    def _system(self, prompt: dict, schema: dict) -> str:
        return (
            str(prompt.get("system", "")) +
            "\n\nReturn exactly one valid JSON object. No markdown. No explanation." +
            "\nJSON Schema:\n" +
            json.dumps(schema, ensure_ascii=False, indent=2)
        )

    def _parse_json(self, content: str) -> dict:
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?", "", content).strip()
            content = re.sub(r"```$", "", content).strip()
        return json.loads(content)
