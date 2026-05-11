class OllamaClient:
    async def complete(self, prompt: str, model: str) -> dict:
        return {"provider": "ollama", "model": model, "output": prompt}
