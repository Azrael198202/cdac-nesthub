import asyncio

import pytest

from ai_core.presentation.structured_fact_normalizer import StructuredFactNormalizer
from ai_core.presentation.final_answer_synthesizer import FinalAnswerSynthesizer
from ai_core.llm.provider_router import ProviderRouter
from ai_core.events.event_bus import event_bus


class _MissingSecretHandler:
    async def generate_json(self, **kwargs):
        raise Exception("MISSING_SECRET:OPENAI_API_KEY")


class _Registry:
    def get(self, provider_type):
        return _MissingSecretHandler()


class _Loader:
    def load_yaml(self, path):
        return {
            "default_route": ["openai"],
            "providers": {
                "openai": {
                    "enabled": True,
                    "type": "universal_model",
                    "model": "test-model",
                    "auth_env": "OPENAI_API_KEY",
                }
            },
        }


def test_structured_fact_normalizer_converts_debug_material_to_facts():
    normalizer = StructuredFactNormalizer()
    materials = [
        {
            "source": "test",
            "status": "success",
            "content": {
                "text": "Matched Parameter: may 16; Text: location page; Values: ['2026', '0 mm', '26 °', '15 °']",
                "source_url": "https://example.test/evidence",
            },
        }
    ]
    state = {"runtime_variables": [{"name": "date", "aliases": ["2026-05-16", "may 16", "16"]}]}
    facts = normalizer.normalize(materials=materials, state=state)
    assert facts
    assert any(f.get("kind") == "observed_value" for f in facts)
    assert all("Matched Parameter:" not in str(f.get("value")) for f in facts if f.get("kind") == "observed_value")


@pytest.mark.asyncio
async def test_final_answer_synthesizer_blocks_debug_material_when_model_unavailable():
    synth = FinalAnswerSynthesizer()
    synth.router = ProviderRouter()
    synth.router.loader = _Loader()
    synth.router.registry = _Registry()
    result = await synth.synthesize(
        run_id="test_run_v70_29",
        node_id="output",
        state={
            "input": "Could you check this?",
            "runtime_variables": [{"name": "date", "aliases": ["2026-05-16", "16"]}],
        },
        materials=[
            {
                "source": "test",
                "status": "success",
                "content": "Matched Parameter: 2026-05-16; Text: data row; Values: ['26 °', '15 °', '0 mm']",
            }
        ],
        trust_summary={"verified_real_execution": True},
    )
    assert "Matched Parameter:" not in result["answer"]
    assert "Descriptors:" not in result["answer"]
    assert "Values:" not in result["answer"]
    assert result["result_material"][0]["content"]["normalized_facts"]


@pytest.mark.asyncio
async def test_provider_router_missing_secret_emits_interaction_and_continues_to_failure():
    router = ProviderRouter()
    router.loader = _Loader()
    router.registry = _Registry()
    run_id = "test_missing_secret_v70_29"
    with pytest.raises(Exception):
        await router.generate_json(
            run_id=run_id,
            node_id="node",
            adapter={"provider_route": ["openai"]},
            prompt={"system": "test"},
            rendered_user_prompt="{}",
            schema={"type": "object"},
        )
    q = event_bus.queue(run_id)
    events = []
    while not q.empty():
        events.append(await q.get())
    assert any(e.get("type") == "INTERACTION_REQUEST" and e.get("secret_key") == "OPENAI_API_KEY" for e in events)
