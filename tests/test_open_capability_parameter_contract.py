import asyncio
import tempfile

from auxiliary_brain.parameters.agent_parameter_contract import AgentParameterContractService
from auxiliary_brain.storage import JsonStore
from auxiliary_brain.studio.service import AgentStudioService


def test_open_capability_fallback_contract_collects_generic_task_input():
    service = AgentParameterContractService()
    contract = service._open_capability_fallback_contract(source="test")
    assert contract["parameters"][0]["name"] == "task_input"
    assert contract["missing_information"][0]["name"] == "task_input"


def test_content_output_fallback_contract_collects_structured_constraints():
    service = AgentParameterContractService()
    contract = service._fallback_contract_for_objective("can write articles", source="test")
    names = [p.get("name") for p in contract.get("parameters", [])]
    assert names == [
        "subject",
        "size_constraint",
        "style_constraint",
        "audience_context",
        "output_language",
        "source_policy",
    ]
    missing = [p.get("name") for p in contract.get("missing_information", [])]
    assert "subject" in missing and "size_constraint" in missing and "source_policy" in missing


def test_open_capability_agent_execution_pauses_for_structured_runtime_input():
    async def scenario():
        with tempfile.TemporaryDirectory() as root:
            studio = AgentStudioService(store=JsonStore(root))
            await studio.create_participant(
                'Create an agent named "Writing Agent" that can write articles.',
                name="Writing Agent",
            )
            participant = studio.store.list_json("generated/agents")[0]
            contract = participant.get("parameter_contract") or {}
            names = [p.get("name") for p in contract.get("parameters", [])]
            assert "subject" in names
            assert "task_input" not in names
            studio.create_task_graph("Execute Writing Agent", name="task_open_capability")
            result = await studio.execute_task("task_open_capability")
            assert result.get("status") == "requires_input"
            fields = (((result.get("pending_action") or {}).get("request") or {}).get("fields") or [])
            field_names = [f.get("parameter_name") or f.get("field") or f.get("name") for f in fields]
            assert "subject" in field_names

    asyncio.run(scenario())


def test_content_output_sparse_runtime_contract_is_enriched():
    service = AgentParameterContractService()
    contract = service._ensure_content_output_contract_shape(
        {"contract_type": "agent_parameter_contract", "parameters": [
            {"name": "subject", "label": "Subject", "description": "Main request", "required": True, "type": "list", "values": []}
        ]},
        source="test_enriched",
    )
    names = [p.get("name") for p in contract.get("parameters", [])]
    assert {"subject", "size_constraint", "style_constraint", "audience_context", "source_policy"}.issubset(set(names))
    missing = [p.get("name") for p in contract.get("missing_information", [])]
    assert "subject" in missing and "size_constraint" in missing and "source_policy" in missing


def test_studio_task_selection_dedupes_duplicate_participants_by_capability():
    with tempfile.TemporaryDirectory() as root:
        studio = AgentStudioService(store=JsonStore(root))
        older = {"participant_id": "p1", "name": "Reusable Agent", "execution_objective": "can produce content", "created_at": "2026-01-01T00:00:00Z"}
        newer = {"participant_id": "p2", "name": "Reusable Agent", "execution_objective": "can produce content", "created_at": "2026-01-02T00:00:00Z"}
        selected = studio._select_participants_for_instruction("Create task which calls Reusable Agent", [older, newer])
        assert len(selected) == 1
        assert selected[0]["participant_id"] == "p2"
