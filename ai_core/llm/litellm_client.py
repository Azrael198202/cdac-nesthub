class LiteLLMClient:
    async def complete(self, prompt: str, model: str) -> dict:
        return {"provider": "litellm", "model": model, "output": prompt}
