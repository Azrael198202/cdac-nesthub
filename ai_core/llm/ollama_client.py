from __future__ import annotations

from typing import Any

import httpx

from ai_core.llm.base import BaseLLMClient, LLMResult


class OllamaClient(BaseLLMClient):
    def __init__(self, model: str = "qwen3:4b", host: str = "http://127.0.0.1:11434") -> None:
        self.model = model
        self.host = host.rstrip("/")

    async def generate(self, prompt: str, **kwargs: Any) -> LLMResult:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(f"{self.host}/api/generate", json={"model": self.model, "prompt": prompt, "stream": False})
                if resp.status_code >= 400:
                    return LLMResult(text="", provider="ollama", model=self.model, ok=False, meta={"error": resp.text})
                data = resp.json()
                return LLMResult(text=data.get("response", ""), provider="ollama", model=self.model)
        except Exception as e:
            return LLMResult(text="", provider="ollama", model=self.model, ok=False, meta={"error": str(e)})
