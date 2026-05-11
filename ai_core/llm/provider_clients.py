from __future__ import annotations
from typing import Any
import os
import httpx


class LLMProviderClient:
    async def generate(self, provider: str, prompt: str, config: dict[str, Any]) -> dict[str, Any]:
        if provider == "ollama":
            return await self._ollama(prompt, config)
        if provider == "openai":
            return await self._openai(prompt, config)
        if provider == "huggingface":
            return {"ok": False, "error": "huggingface_runtime_adapter_not_generated"}
        return {"ok": False, "error": f"unsupported_provider:{provider}"}

    async def _ollama(self, prompt: str, config: dict[str, Any]) -> dict[str, Any]:
        base_url = config.get("base_url", "http://127.0.0.1:11434").rstrip("/")
        model = (config.get("models") or ["qwen3:4b"])[0]
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(f"{base_url}/api/generate", json={"model": model, "prompt": prompt, "stream": False})
            if resp.status_code >= 400:
                return {"ok": False, "error": resp.text}
            data = resp.json()
            return {"ok": True, "provider": "ollama", "model": model, "text": data.get("response", "")}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def _openai(self, prompt: str, config: dict[str, Any]) -> dict[str, Any]:
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            return {"ok": False, "error": "missing_OPENAI_API_KEY"}
        base_url = config.get("base_url", "https://api.openai.com/v1").rstrip("/")
        model = config.get("model", "gpt-4o-mini")
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {key}"},
                    json={"model": model, "messages": [{"role": "user", "content": prompt}]},
                )
            if resp.status_code >= 400:
                return {"ok": False, "error": resp.text}
            data = resp.json()
            return {"ok": True, "provider": "openai", "model": model, "text": data["choices"][0]["message"]["content"]}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
