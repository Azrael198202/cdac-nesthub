from __future__ import annotations

import os
import sys

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1]))

from ai_core.model_orchestration.brain_model_router import BrainModelRoute
from ai_core.model_orchestration.litellm_brain_client import LiteLLMBrainClient


def test_provider_secret_request_and_model_exact_match() -> None:
    client = LiteLLMBrainClient()
    os.environ.pop('OPENAI_API_KEY', None)
    route = BrainModelRoute(
        brain='auxiliary_brain',
        task_type='runtime_tool_code_generation',
        complexity='high',
        provider='openai',
        model='gpt-5.5-thinking',
        options={'temperature': 0},
        fallback=[],
        decision_reason='verification',
    )
    assert client._missing_provider_secret(route) == 'OPENAI_API_KEY'
    cleaned = client._sanitize_provider_options(route=route, options={'temperature': 0})
    assert cleaned['temperature'] == 1
    assert cleaned['drop_params'] is True
    assert client._ollama_model_exists(['qwen3.5:2b'], 'qwen3.5:4b-q4_k_m') is False


if __name__ == '__main__':
    test_provider_secret_request_and_model_exact_match()
    print('v23.7 provider secret and model prepare verification passed')
