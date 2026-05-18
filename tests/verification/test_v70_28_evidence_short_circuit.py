import asyncio

from ai_core.execution.evidence_satisfied_short_circuit import EvidenceSatisfiedShortCircuit
from ai_core.executors.tool_call_executor import ToolCallExecutor


def _runtime_fixture():
    text = (
        "Target Entity information for 2026-05-16. "
        "Detailed values include 7% probability, 16 / 23 °C range, and other planning details."
    )
    return {
        "request_type": "runtime_tool_artifact_generation",
        "capability": "generic_information_access",
        "step": {
            "step_id": "step_1",
            "task_id": "step_1",
            "step_type": "retrieve_information",
            "objective": "Retrieve information for Target Entity on 2026-05-16",
            "parameters": {"known": {"location": "Target Entity", "date": "2026-05-16"}, "missing_required": {}, "optional": {}},
            "required_capability": "generic_information_access",
            "execution_strategy": ["web_evidence", "tool_generation"],
            "execution_ready": True,
        },
        "user_input": "Could you check Target Entity for the requested value?",
        "api_discovery": {
            "status": "success",
            "strategy_used": "fetched_page_answer_sufficiency",
            "endpoint_verification": {"verified_json_api": False, "recommended_tool_type": "direct_answer"},
            "selected_evidence": [
                {
                    "url": "https://example.test/item/2026-05-16",
                    "title": "Target Entity details for 2026-05-16",
                    "source": "web_evidence",
                    "confidence": 0.95,
                    "coverage": {"passed": True, "coverage_ratio": 1, "matched": {"location": ["Target Entity"], "date": ["16"]}, "missing": []},
                    "text_excerpt": text,
                }
            ],
        },
        "external_solution_discovery": {},
    }


def test_evidence_satisfied_short_circuit_detects_sufficient_evidence():
    fixture = _runtime_fixture()
    assert EvidenceSatisfiedShortCircuit().should_bypass_generated_execution(fixture["api_discovery"]) is True


def test_direct_evidence_execution_returns_success_before_codegen():
    fixture = _runtime_fixture()
    executor = ToolCallExecutor()

    async def run():
        return await executor._try_direct_evidence_execution_from_discovery(
            run_id="test",
            node_id="execution",
            step_id="step_1",
            capability=fixture["capability"],
            step=fixture["step"],
            state={"input": fixture["user_input"]},
            api_discovery=fixture["api_discovery"],
            external_discovery=fixture["external_solution_discovery"],
            reason="test_short_circuit",
        )

    result = asyncio.run(run())
    assert result is not None
    assert result["status"] == "success"
    assert result["result"]["status"] == "success"
    assert result["result"]["data"]["structured_materialized"] is True
