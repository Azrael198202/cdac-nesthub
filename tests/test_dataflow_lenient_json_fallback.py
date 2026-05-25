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
