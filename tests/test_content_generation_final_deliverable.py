import asyncio

from ai_core.executors.tool_call_executor import ToolCallExecutor
from ai_core.workflow.workflow_contract_builder import WorkflowContractBuilder


def test_planner_instruction_is_preserved_for_executor_generation():
    builder = WorkflowContractBuilder()
    result = {
        "action_planning_record": {
            "planner_llm_action_ranking": [
                {
                    "action_type": "llm_generate",
                    "content": "Produce the final requested text using the confirmed constraints.",
                }
            ],
            "substep_generation": [
                {
                    "substep": "Generate final content.",
                    "parameters": {"topic": "sample place", "length": "120 words"},
                }
            ],
        },
        "planned_steps": [
            {
                "step_id": "step_1",
                "action_type": "llm_generate",
                "objective": "can produce content",
                "parameters": {"known": {"topic": "sample place", "length": "120 words"}},
            }
        ],
    }
    normalized = builder.normalize_workflow_result(result=result, state={"results": {}}, slim_user_input="")
    step = normalized["planned_steps"][0]
    assert step["execution_method"] == "content_generation"
    assert "Produce the final requested text" in step["execution_instruction"]
    assert "120 words" in step["execution_instruction"]


def test_content_generation_rejects_short_parameter_summary():
    executor = ToolCallExecutor()
    quality = executor._generated_answer_quality(
        answer="Writing Agent can write a 200-word article about Fukuoka for foreigners.",
        step={"objective": "can write articles"},
        known={"length": "200 words"},
    )
    assert quality["passed"] is False
    assert quality["reason"] in {"answer_looks_like_request_summary", "answer_too_short_for_requested_size"}


def test_content_generation_uses_executor_instruction_and_returns_final_material():
    class FakeProvider:
        def __init__(self):
            self.rendered_user_prompt = ""

        async def generate_json(self, **kwargs):
            self.rendered_user_prompt = kwargs["rendered_user_prompt"]
            self.node_id = kwargs.get("node_id")
            return {
                "status": "success",
                "answer_material": "Fukuoka is an easy city to enjoy from the moment you arrive. The airport is close to the center, the food is friendly, and the streets feel relaxed. Visitors can start around Hakata, try ramen or fresh seafood, then move to Tenjin for shopping and cafes. For a slower afternoon, Ohori Park is a comfortable place to walk, rest, and watch local life. The city also gives quick access to the sea, temples, and nearby day trips. It feels welcoming without being overwhelming, which makes it a great first stop in Kyushu for travelers who want culture, food, and convenience in one place.",
                "normalized_facts": [],
            }

    async def scenario():
        executor = ToolCallExecutor()
        fake = FakeProvider()
        executor.provider_router = fake
        result = await executor._try_model_generation_execution(
            run_id="r1",
            node_id="execution",
            step_id="step_1",
            capability="generic_runtime_capability",
            step={
                "objective": "can write articles",
                "execution_instruction": "Write a casual article about Fukuoka for foreign visitors, around 120 words, without references.",
                "parameters": {"known": {"topic": "Fukuoka", "length": "120 words", "audience": "foreign visitors"}},
            },
            state={"input": "runtime request"},
        )
        assert result is not None
        assert result["result"]["data"]["answer_material"].startswith("Fukuoka is")
        assert "FINAL_DELIVERABLE_REQUEST=Write a casual article" in fake.rendered_user_prompt
        assert "not a requirements summary" in fake.rendered_user_prompt
        assert fake.node_id == "content_generation_execution"

    asyncio.run(scenario())


def test_invalid_planner_action_with_executor_material_uses_content_generation():
    builder = WorkflowContractBuilder()
    state = {
        "results": {
            "input_parsing": {"parsed_entities": {"confirmed": "value"}},
            "requirement_completion": {"requirement_record": {"known_parameters": {"confirmed": "value"}, "missing_information": []}},
        }
    }
    result = {
        "action_planning_record": {
            "planner_output": {
                "selected_action_type": "planner_only_internal_label",
                "content": "Produce the final deliverable from the confirmed parameters.",
            }
        },
        "planned_steps": [
            {
                "step_id": "step_1",
                "action_type": "planner_only_internal_label",
                "objective": "produce requested result",
                "parameters": {"known": {"confirmed": "value"}, "missing_required": {}, "optional": {}},
            }
        ],
    }
    normalized = builder.normalize_workflow_result(result=result, state=state, slim_user_input="")
    step = normalized["planned_steps"][0]
    assert normalized["execution_decision"]["selected_action_type"] == "llm_generate"
    assert step["action_type"] == "llm_generate"
    assert step["execution_method"] == "content_generation"


def test_structural_fallback_still_asks_user_when_missing_required_input():
    builder = WorkflowContractBuilder()
    state = {
        "results": {
            "requirement_completion": {"requirement_record": {"missing_information": ["required_value"]}},
        }
    }
    result = {"action_planning_record": {"planner_output": {"content": "Prepare final output."}}}
    normalized = builder.normalize_workflow_result(result=result, state=state, slim_user_input="")
    assert normalized["execution_decision"]["selected_action_type"] == "ask_user"
    assert normalized["planned_steps"][0]["execution_method"] == "human_interaction"
