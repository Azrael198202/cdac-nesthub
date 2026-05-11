from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    ok: bool = True
    meta: dict[str, Any] | None = None


class BaseLLMClient:
    async def generate(self, prompt: str, **kwargs: Any) -> LLMResult:
        raise NotImplementedError
