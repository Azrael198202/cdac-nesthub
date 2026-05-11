from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class LLMResult:
    ok: bool
    provider: str
    content: str
    error: str | None = None


class LocalRuleProvider:
    name = "local_rules"

    async def complete(self, prompt: str, user_input: str, context: dict[str, Any]) -> LLMResult:
        # Generic deterministic helper only. It does not pretend to complete tasks.
        lowered = user_input.strip().lower()
        payload = {
            "analysis_source": "local_rules",
            "cleaned_input": user_input.strip(),
            "language": "unknown",
            "confidence": 0.35 if lowered else 0.0,
            "missing_information": [],
            "note": "Local rules can structure text, but a real LLM is recommended for semantic planning.",
        }
        return LLMResult(ok=True, provider=self.name, content=json.dumps(payload, ensure_ascii=False))


class OllamaProvider:
    name = "ollama"

    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def complete(self, prompt: str, user_input: str, context: dict[str, Any]) -> LLMResult:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt + "\n\nUser input:\n" + user_input + "\n\nContext:\n" + json.dumps(context, ensure_ascii=False),
                        "stream": False,
                    },
                )
                if resp.status_code != 200:
                    return LLMResult(False, self.name, "", f"Ollama HTTP {resp.status_code}: {resp.text[:300]}")
                data = resp.json()
                return LLMResult(True, self.name, data.get("response", ""))
        except Exception as e:
            return LLMResult(False, self.name, "", str(e))


class OpenAIProvider:
    name = "openai"

    def __init__(self, model: str, api_key: str | None = None) -> None:
        self.model = model
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")

    async def complete(self, prompt: str, user_input: str, context: dict[str, Any]) -> LLMResult:
        if not self.api_key:
            return LLMResult(False, self.name, "", "OPENAI_API_KEY is not configured")
        try:
            async with httpx.AsyncClient(timeout=90) as client:
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
                    return LLMResult(False, self.name, "", f"OpenAI HTTP {resp.status_code}: {resp.text[:300]}")
                data = resp.json()
                return LLMResult(True, self.name, data["choices"][0]["message"]["content"])
        except Exception as e:
            return LLMResult(False, self.name, "", str(e))
