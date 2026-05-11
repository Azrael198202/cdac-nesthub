from __future__ import annotations

from typing import Any

from ai_core.llm.base import BaseLLMClient, LLMResult


class HuggingFaceClient(BaseLLMClient):
    """Placeholder adapter. Runtime can register downloaded HF models without changing ai_core."""

    def __init__(self, model: str = "hf-candidate-placeholder") -> None:
        self.model = model

    async def generate(self, prompt: str, **kwargs: Any) -> LLMResult:
        return LLMResult(
            text="",
            provider="huggingface",
            model=self.model,
            ok=False,
            meta={"error": "hf_model_not_downloaded", "recommendation": "download_or_register_model_in_runtime"},
        )
