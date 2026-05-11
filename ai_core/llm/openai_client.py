class OpenAIClient:
    async def complete(self, prompt: str, model: str) -> dict:
        return {"provider": "openai", "model": model, "output": prompt}
