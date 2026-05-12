import httpx
from ai_core.events.event_bus import event_bus
from ai_core.llm.provider_handlers.base import ProviderUnavailableError
from ai_core.llm.provider_handlers.utils import build_system_prompt, parse_json_content
from ai_core.secrets.secret_store import SecretStore


class OpenAICompatibleProviderHandler:
    provider_type = "openai_compatible"

    def __init__(self) -> None:
        self.secret_store = SecretStore()

    async def generate_json(self, *, run_id: str, node_id: str, provider_name: str, provider: dict, prompt: dict, rendered_user_prompt: str, schema: dict) -> dict:
        base_url = provider.get("base_url")
        if not base_url:
            raise ProviderUnavailableError(f"{provider_name}: base_url is required")

        endpoint = provider.get("endpoint", "/v1/chat/completions")
        url = base_url.rstrip("/") + endpoint
        key = ""
        key_name = provider.get("api_key_env")
        if key_name:
            key = self.secret_store.get(key_name) or ""

        model = provider.get("model")
        timeout = provider.get("timeout_seconds", 120)

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": build_system_prompt(prompt, schema)},
                {"role": "user", "content": rendered_user_prompt},
            ],
        }

        if provider.get("response_format_json", True):
            payload["response_format"] = {"type": "json_object"}

        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"

        await event_bus.emit(run_id, {
            "type": "LLM_REQUEST_SENT",
            "title": "LLM request sent",
            "message": f"{provider_name}: waiting for OpenAI-compatible response...",
            "node_id": node_id,
            "provider": provider_name,
            "model": model,
        })

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]

        return parse_json_content(content)
