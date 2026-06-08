from ai_core.model_orchestration.brain_model_router import BrainModelRoute
from ai_core.model_orchestration.litellm_brain_client import LiteLLMBrainClient


def test_partial_route_is_backward_compatible():
    route = BrainModelRoute(provider="local", model="sample")
    payload = route.to_dict()
    assert payload["brain"] == "runtime_brain"
    assert payload["task_type"] == "default"
    assert payload["complexity"] == "default"
    assert payload["provider"] == "local"
    assert payload["model"] == "sample"


def test_fallback_route_keeps_normalized_context():
    client = LiteLLMBrainClient()
    base = BrainModelRoute(
        brain="auxiliary_brain",
        task_type="runtime_code_generation",
        complexity="basic",
        provider="local",
        model="primary",
        options={"temperature": 0},
    )
    fb = client._fallback_route(base=base, item={"provider": "local", "model": "fallback"})
    assert fb.brain == "auxiliary_brain"
    assert fb.task_type == "runtime_code_generation"
    assert fb.complexity == "basic"
    assert fb.model == "fallback"


if __name__ == "__main__":
    test_partial_route_is_backward_compatible()
    test_fallback_route_keeps_normalized_context()
    print("v23.10 route compatibility verification passed")
