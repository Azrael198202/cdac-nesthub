from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, AsyncGenerator

import httpx


@dataclass
class LLMResult:
    ok: bool
    provider: str
    content: str
    error: str | None = None


class BaseProvider:
    name = "base"

    async def complete(self, prompt: str, user_input: str, context: dict[str, Any]) -> LLMResult:
        raise NotImplementedError

    async def stream_complete(self, prompt: str, user_input: str, context: dict[str, Any]) -> AsyncGenerator[str, None]:
        result = await self.complete(prompt, user_input, context)
        if not result.ok:
            raise RuntimeError(result.error or "provider failed")
        text = result.content or ""
        # UI-facing stream chunks. Providers with native streaming can override this.
        step = 80
        for i in range(0, len(text), step):
            yield text[i:i + step]


class OllamaProvider(BaseProvider):
    name = "ollama"

    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def complete(self, prompt: str, user_input: str, context: dict[str, Any]) -> LLMResult:
        try:
            async with httpx.AsyncClient(timeout=90) as client:
                resp = await client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt + "\n\nUser input:\n" + user_input + "\n\nContext JSON:\n" + json.dumps(context, ensure_ascii=False),
                        "stream": False,
                    },
                )
                if resp.status_code != 200:
                    return LLMResult(False, self.name, "", f"Ollama HTTP {resp.status_code}: {resp.text[:500]}")
                data = resp.json()
                return LLMResult(True, self.name, data.get("response", ""))
        except Exception as e:
            return LLMResult(False, self.name, "", str(e))


class HuggingFaceEndpointProvider(BaseProvider):
    """Generic HuggingFace Inference API provider.

    This is intentionally generic. It does not contain business logic. Runtime
    config decides which HF model endpoint should be used.
    """

    name = "huggingface"

    def __init__(self, model: str, api_token: str | None = None) -> None:
        self.model = model
        self.api_token = api_token or os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_API_TOKEN")

    async def complete(self, prompt: str, user_input: str, context: dict[str, Any]) -> LLMResult:
        if not self.api_token:
            return LLMResult(False, self.name, "", "HF_TOKEN is not configured")
        try:
            url = f"https://api-inference.huggingface.co/models/{self.model}"
            payload = {
                "inputs": prompt + "\n\nUser input:\n" + user_input + "\n\nContext JSON:\n" + json.dumps(context, ensure_ascii=False),
                "parameters": {"max_new_tokens": 1200, "temperature": 0.2, "return_full_text": False},
            }
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(url, headers={"Authorization": f"Bearer {self.api_token}"}, json=payload)
                if resp.status_code != 200:
                    return LLMResult(False, self.name, "", f"HuggingFace HTTP {resp.status_code}: {resp.text[:500]}")
                data = resp.json()
                if isinstance(data, list) and data and isinstance(data[0], dict):
                    text = data[0].get("generated_text") or data[0].get("summary_text") or json.dumps(data, ensure_ascii=False)
                elif isinstance(data, dict):
                    text = data.get("generated_text") or json.dumps(data, ensure_ascii=False)
                else:
                    text = str(data)
                return LLMResult(True, self.name, text)
        except Exception as e:
            return LLMResult(False, self.name, "", str(e))


class OpenAIProvider(BaseProvider):
    name = "openai"

    def __init__(self, model: str, api_key: str | None = None) -> None:
        self.model = model
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")

    async def complete(self, prompt: str, user_input: str, context: dict[str, Any]) -> LLMResult:
        if not self.api_key:
            return LLMResult(False, self.name, "", "OPENAI_API_KEY is not configured")
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": prompt},
                            {"role": "user", "content": user_input},
                            {"role": "user", "content": "Context JSON: " + json.dumps(context, ensure_ascii=False)},
                        ],
                        "temperature": 0.2,
                    },
                )
                if resp.status_code != 200:
                    return LLMResult(False, self.name, "", f"OpenAI HTTP {resp.status_code}: {resp.text[:500]}")
                data = resp.json()
                return LLMResult(True, self.name, data["choices"][0]["message"]["content"])
        except Exception as e:
            return LLMResult(False, self.name, "", str(e))
