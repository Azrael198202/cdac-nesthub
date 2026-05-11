class LLMClient:
    async def generate_json(self, capability_info: dict, prompt: str, payload: dict) -> dict:
        return {
            "capability_id": capability_info.get("capability_id"),
            "capability_type": capability_info.get("type"),
            "status": "capability_ready",
            "note": "Capability is ready. Runtime prompt/tool adapter can execute this node.",
            "payload_keys": list(payload.keys()),
        }
