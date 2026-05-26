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

    Budgets are read from provider/runtime config and stage policy.  The small
    built-in map is stage-complexity governance, not business logic: it keeps
    early JSON stages light so small local models can satisfy the same schemas
    as larger/API models.
    """

    DEFAULT_BUDGET_TOKENS = 6000
    STAGE_BUDGET_TOKENS = {
        "input_parsing": 1400,
        "intent_recognition": 1600,
        "simple_intent": 1600,
        "requirement_completion": 1800,
        "context_awareness": 1800,
        "capability_classification": 1800,
        "execution_mode_decision": 1800,
        "agent_action_planning": 2600,
        "workflow_planning": 3200,
        "execution_preparation": 2400,
        "pre_execution_validation": 2200,
        "result_verification": 2400,
        "feedback_repair": 2600,
        "final_synthesis": 3600,
    }

    def __init__(self) -> None:
        self.estimator = TokenEstimator()

    def budget_for(self, provider: dict | None = None, adapter: dict | None = None) -> int:
        provider = provider or {}
        adapter = adapter or {}
        configured_default = os.getenv("AI_CORE_MAX_PROMPT_TOKENS") or self.DEFAULT_BUDGET_TOKENS
        stage_id = str(adapter.get("stage_id") or adapter.get("model_stage") or adapter.get("cognitive_stage") or "").strip()
        stage_budget = self.STAGE_BUDGET_TOKENS.get(stage_id)
        raw = int(
            adapter.get("max_prompt_tokens")
            or provider.get("max_prompt_tokens")
            or provider.get("prompt_budget_tokens")
            or stage_budget
            or configured_default
        )
        reserve = int(adapter.get("prompt_budget_safety_tokens") or provider.get("prompt_budget_safety_tokens") or 400)
        return max(800, raw - reserve)

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
