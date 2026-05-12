import httpx
from ai_core.events.event_bus import event_bus
from ai_core.llm.provider_handlers.base import ProviderUnavailableError
from ai_core.llm.provider_handlers.utils import build_system_prompt, parse_json_content
from ai_core.secrets.secret_store import SecretStore


class OpenAIProviderHandler:
    provider_type = "openai"

    def __init__(self) -> None:
        self.secret_store = SecretStore()

    async def generate_json(self, *, run_id: str, node_id: str, provider_name: str, provider: dict, prompt: dict, rendered_user_prompt: str, schema: dict) -> dict:
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
                {"role": "system", "content": build_system_prompt(prompt, schema)},
                {"role": "user", "content": rendered_user_prompt},
            ],
        }

        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

        await event_bus.emit(run_id, {
            "type": "LLM_REQUEST_SENT",
            "title": "LLM request sent",
            "message": f"{provider_name}: waiting for model response...",
            "node_id": node_id,
            "provider": provider_name,
            "model": model,
        })

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]

        return parse_json_content(content)
