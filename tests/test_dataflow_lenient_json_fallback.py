import pytest

from ai_core.agent_delegation.primary_brain_client import AgentExecutionRequest, PrimaryBrainDelegationClient
from ai_core.llm.provider_handlers.utils import LLMJSONParseError


class BrokenJsonRouter:
    async def generate_json(self, **kwargs):
        raise LLMJSONParseError(
            "invalid JSON",
            raw_content="The result is already translated and ready for the user.",
        )


@pytest.mark.asyncio
async def test_dataflow_step_accepts_public_raw_text_when_json_wrapper_fails():
    client = PrimaryBrainDelegationClient()
    client.router = BrokenJsonRouter()
    result = await client.execute_intermediate_step(
        AgentExecutionRequest(
            participant_id="p1",
            participant_name="generic step",
            participant_instruction="Transform the upstream result into a user-facing answer.",
            task_name="task",
            task_instruction="task",
            community_id="c",
            shared_context={"available_peer_results": [{"participant_name": "upstream", "final_answer": "source text"}]},
        )
    )
    assert result.status == "completed"
    assert "translated" in result.final_answer
    assert result.workflow_results["dataflow_step"]["execution_mode"] == "lean_llm_raw_text_fallback"


class BrokenJsonObjectRouter:
    async def generate_json(self, **kwargs):
        raise LLMJSONParseError(
            "invalid JSON",
            raw_content='Here is the result: {"final_answer": "Clean public answer"}',
        )


@pytest.mark.asyncio
async def test_dataflow_step_extracts_final_answer_from_raw_json_fragment():
    client = PrimaryBrainDelegationClient()
    client.router = BrokenJsonObjectRouter()
    result = await client.execute_intermediate_step(
        AgentExecutionRequest(
            participant_id="p1",
            participant_name="generic step",
            participant_instruction="Transform the upstream result into a user-facing answer.",
            task_name="task",
            task_instruction="task",
            community_id="c",
            shared_context={"available_peer_results": [{"participant_name": "upstream", "final_answer": "source text"}]},
        )
    )
    assert result.status == "completed"
    assert result.final_answer == "Clean public answer"

class RefusalRouter:
    async def generate_json(self, **kwargs):
        raise LLMJSONParseError(
            "invalid JSON",
            raw_content="The requested participants are not available in this environment. I cannot perform the requested actions.",
        )


@pytest.mark.asyncio
async def test_dataflow_step_rejects_generic_refusal_as_result_material():
    client = PrimaryBrainDelegationClient()
    client.router = RefusalRouter()
    result = await client.execute_intermediate_step(
        AgentExecutionRequest(
            participant_id="p1",
            participant_name="generic step",
            participant_instruction="Transform the upstream result into a user-facing answer.",
            task_name="task",
            task_instruction="task",
            community_id="c",
            shared_context={"available_peer_results": [{"participant_name": "upstream", "final_answer": "source text"}]},
        )
    )
    assert result.status == "failed"
    assert "not available in this environment" not in result.final_answer.lower()


@pytest.mark.asyncio
async def test_dataflow_step_missing_declared_upstream_does_not_call_model():
    class ExplodingRouter:
        async def generate_json(self, **kwargs):
            raise AssertionError("model should not be called without upstream material")

    client = PrimaryBrainDelegationClient()
    client.router = ExplodingRouter()
    result = await client.execute_intermediate_step(
        AgentExecutionRequest(
            participant_id="p1",
            participant_name="generic step",
            participant_instruction="Transform declared upstream results.",
            task_name="task",
            task_instruction="task",
            community_id="c",
            shared_context={"depends_on": ["upstream_id"], "available_peer_results": []},
        )
    )
    assert result.status == "failed"
    assert "upstream" in result.final_answer.lower()

class InspectingPlainTextRouter:
    def __init__(self):
        self.kwargs = None

    async def generate_json(self, **kwargs):
        self.kwargs = kwargs
        return {"final_answer": "Translated public result with complete upstream material."}


@pytest.mark.asyncio
async def test_dataflow_step_uses_plain_text_prompt_and_larger_completion_budget():
    router = InspectingPlainTextRouter()
    client = PrimaryBrainDelegationClient()
    client.router = router
    result = await client.execute_intermediate_step(
        AgentExecutionRequest(
            participant_id="p1",
            participant_name="generic step",
            participant_instruction="Transform both upstream results into the requested language.",
            task_name="task",
            task_instruction="task",
            community_id="c",
            shared_context={
                "available_peer_results": [
                    {"participant_name": "a", "final_answer": "first input"},
                    {"participant_name": "b", "final_answer": "second input"},
                ]
            },
        )
    )
    assert result.status == "completed"
    assert result.final_answer == "Translated public result with complete upstream material."
    assert router.kwargs["prompt"]["system"] == "Output only the requested result text. No JSON. No explanation."
    assert router.kwargs["adapter"]["provider_options"]["num_predict"] >= 300
    assert "final_answer" not in router.kwargs["rendered_user_prompt"]


class TruncatedJsonRouter:
    async def generate_json(self, **kwargs):
        return {"final_answer": '{"final_answer":"Visible result without wrapper'}


@pytest.mark.asyncio
async def test_dataflow_step_unwraps_truncated_json_wrapper_from_lenient_router():
    client = PrimaryBrainDelegationClient()
    client.router = TruncatedJsonRouter()
    result = await client.execute_intermediate_step(
        AgentExecutionRequest(
            participant_id="p1",
            participant_name="generic step",
            participant_instruction="Transform upstream result into final output.",
            task_name="task",
            task_instruction="task",
            community_id="c",
            shared_context={"available_peer_results": [{"participant_name": "upstream", "final_answer": "source text"}]},
        )
    )
    assert result.status == "completed"
    assert result.final_answer == "Visible result without wrapper"
    assert not result.final_answer.startswith("{")
