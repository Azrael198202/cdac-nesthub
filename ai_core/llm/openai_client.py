from __future__ import annotations

from typing import Any

import httpx

from ai_core.config.io import read_json
from ai_core.config.paths import RUNTIME_SECRETS_DIR
from ai_core.llm.base import BaseLLMClient, LLMResult


class OpenAIClient(BaseLLMClient):
    def __init__(self, model: str = "gpt-4.1-mini") -> None:
        self.model = model

    def _api_key(self) -> str | None:
        data = read_json(RUNTIME_SECRETS_DIR / "local_secrets.json", {"providers": {}})
        return data.get("providers", {}).get("openai", {}).get("api_key")

    async def generate(self, prompt: str, **kwargs: Any) -> LLMResult:
        key = self._api_key()
        if not key:
            return LLMResult(text="", provider="openai", model=self.model, ok=False, meta={"error": "missing_api_key"})
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": "You are a strict reviewer and planner. Return JSON when asked."},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": kwargs.get("temperature", 0.2),
                    },
                )
                data = resp.json()
                if resp.status_code >= 400:
                    return LLMResult(text="", provider="openai", model=self.model, ok=False, meta={"error": data})
                return LLMResult(text=data["choices"][0]["message"]["content"], provider="openai", model=self.model)
        except Exception as e:
            return LLMResult(text="", provider="openai", model=self.model, ok=False, meta={"error": str(e)})
