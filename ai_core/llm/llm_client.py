class LLMClient:
    async def generate_json(self, provider_info: dict, prompt: str, payload: dict) -> dict:
        return {
            "provider": provider_info.get("provider"),
            "model": provider_info.get("model"),
            "status": "provider_ready",
            "note": "Provider is ready. Runtime prompt/tool adapter can execute this node.",
            "payload_keys": list(payload.keys()),
        }
