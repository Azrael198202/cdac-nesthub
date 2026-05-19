from __future__ import annotations

import os
from dataclasses import dataclass
from ai_core.context.token_estimator import TokenEstimator


@dataclass
class PromptBudgetResult:
    text: str
    estimated_tokens: int
    budget_tokens: int
    truncated: bool


class PromptBudgetManager:
    """Generic prompt budget manager.

    Budgets are read from provider/runtime config, not hardcoded per provider.
    """

    DEFAULT_BUDGET_TOKENS = 6000

    def __init__(self) -> None:
        self.estimator = TokenEstimator()

    def budget_for(self, provider: dict | None = None, adapter: dict | None = None) -> int:
        provider = provider or {}
        adapter = adapter or {}
        configured_default = os.getenv("AI_CORE_MAX_PROMPT_TOKENS") or self.DEFAULT_BUDGET_TOKENS
        raw = int(
            adapter.get("max_prompt_tokens")
            or provider.get("max_prompt_tokens")
            or provider.get("prompt_budget_tokens")
            or configured_default
        )
        reserve = int(adapter.get("prompt_budget_safety_tokens") or provider.get("prompt_budget_safety_tokens") or 1000)
        return max(1000, raw - reserve)

    def fit_text(self, text: str, *, budget_tokens: int) -> PromptBudgetResult:
        estimated = self.estimator.estimate_text(text)
        if estimated <= budget_tokens:
            return PromptBudgetResult(text=text, estimated_tokens=estimated, budget_tokens=budget_tokens, truncated=False)
        max_chars = max(1000, int(budget_tokens * self.estimator.CHARS_PER_TOKEN))
        reduced = text[:max_chars] + "\n...[prompt truncated by PromptBudgetManager]"
        return PromptBudgetResult(
            text=reduced,
            estimated_tokens=self.estimator.estimate_text(reduced),
            budget_tokens=budget_tokens,
            truncated=True,
        )
