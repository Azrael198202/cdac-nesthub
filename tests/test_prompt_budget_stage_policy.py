from __future__ import annotations

from ai_core.context.prompt_budget_manager import PromptBudgetManager
from ai_core.runtime.modeling.model_stage_policy import ModelStagePolicy


def test_stage_budget_prefers_smaller_early_stage_budget() -> None:
    manager = PromptBudgetManager()
    early = manager.budget_for(adapter={"stage_id": "input_parsing"})
    final = manager.budget_for(adapter={"stage_id": "final_synthesis"})
    assert early < final
    assert early >= 800


def test_stage_policy_aliases_common_runtime_stages() -> None:
    policy = ModelStagePolicy()
    assert policy.stage_for(node_id="intent_recognition", adapter={}) == "simple_intent"
    assert policy.stage_for(node_id="agent_action_planning", adapter={"model_stage": "agent_action_planning"}) == "agent_action_planning"
