from __future__ import annotations
import shutil
import httpx


class ProviderChecker:
    async def check_binary(self, binary: str | None) -> dict:
        if not binary:
            return {"required": False, "available": True}
        path = shutil.which(binary)
        return {"required": True, "available": bool(path), "path": path}

    async def check_http(self, url: str | None) -> dict:
        if not url:
            return {"required": False, "available": True}
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                resp = await client.get(url)
            return {"required": True, "available": resp.status_code < 500, "status_code": resp.status_code}
        except Exception as exc:
            return {"required": True, "available": False, "error": str(exc)}

    async def check_ollama_model(self, base_url: str, model: str) -> dict:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{base_url.rstrip('/')}/api/tags")
            data = resp.json()
            names = [m.get("name") for m in data.get("models", [])]
            return {"available": model in names, "models": names}
        except Exception as exc:
            return {"available": False, "error": str(exc)}
