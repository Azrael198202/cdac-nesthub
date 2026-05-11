from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ai_core.config.io import read_yaml, write_yaml
from ai_core.config.paths import RUNTIME_MODELS_DIR
from ai_core.llm.huggingface_client import HuggingFaceClient
from ai_core.llm.local_rule_client import LocalRuleClient
from ai_core.llm.ollama_client import OllamaClient
from ai_core.llm.openai_client import OpenAIClient


@dataclass
class RouteDecision:
    provider: str
    model: str
    reason: str


class ModelRouter:
    def __init__(self) -> None:
        self.routes_file = RUNTIME_MODELS_DIR / "model_routes.yaml"

    def ensure_default_routes(self) -> None:
        if self.routes_file.exists():
            return
        write_yaml(self.routes_file, {
            "routes": {
                "input_parsing": [{"provider": "local", "model": "local-rule-v1"}, {"provider": "ollama", "model": "qwen3:4b"}, {"provider": "openai", "model": "gpt-4.1-mini"}],
                "intent_recognition": [{"provider": "local", "model": "local-rule-v1"}, {"provider": "ollama", "model": "qwen3:4b"}, {"provider": "openai", "model": "gpt-4.1-mini"}],
                "context_awareness": [{"provider": "local", "model": "local-rule-v1"}, {"provider": "openai", "model": "gpt-4.1-mini"}],
                "workflow_planning": [{"provider": "local", "model": "local-rule-v1"}, {"provider": "ollama", "model": "qwen3:4b"}, {"provider": "openai", "model": "gpt-4.1-mini"}],
                "execution": [{"provider": "local", "model": "local-rule-v1"}, {"provider": "openai", "model": "gpt-4.1-mini"}],
                "feedback_learning": [{"provider": "local", "model": "local-rule-v1"}, {"provider": "openai", "model": "gpt-4.1-mini"}],
                "review": [{"provider": "local", "model": "local-rule-v1"}, {"provider": "openai", "model": "gpt-4.1-mini"}],
            },
            "policy": {"local_first": True, "hf_second": True, "external_api_last": True, "human_review_required": True}
        })

    def get_candidates(self, step: str) -> list[dict[str, str]]:
        self.ensure_default_routes()
        data = read_yaml(self.routes_file, {})
        return data.get("routes", {}).get(step, data.get("routes", {}).get("review", []))

    def client_for(self, provider: str, model: str):
        if provider == "local":
            return LocalRuleClient(model)
        if provider == "ollama":
            return OllamaClient(model)
        if provider == "huggingface":
            return HuggingFaceClient(model)
        if provider == "openai":
            return OpenAIClient(model)
        return LocalRuleClient("local-rule-v1")

    async def generate_with_route(self, step: str, prompt: str, **kwargs: Any):
        errors = []
        for cand in self.get_candidates(step):
            client = self.client_for(cand["provider"], cand["model"])
            result = await client.generate(prompt, **kwargs)
            if result.ok and result.text:
                return result
            errors.append({"provider": cand["provider"], "model": cand["model"], "meta": result.meta})
        return LocalRuleClient().generate(prompt, **kwargs)
