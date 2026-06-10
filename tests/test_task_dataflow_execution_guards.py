import pytest

from ai_core.agent_delegation.primary_brain_client import AgentExecutionRequest, AgentExecutionResult, PrimaryBrainDelegationClient
from auxiliary_brain.studio.service import AgentStudioService


@pytest.mark.asyncio
async def test_standalone_generated_step_uses_primary_runtime_not_lean_llm(monkeypatch):
    client = PrimaryBrainDelegationClient()
    called = {}

    async def fake_execute_agent_request(request, progress_callback=None):
        called['used_primary_runtime'] = True
        return AgentExecutionResult(
            participant_id=request.participant_id,
            participant_name=request.participant_name,
            core_run_id='core_primary',
            status='completed',
            final_answer='verified current result',
            workflow_results={'execution': {'status': 'completed'}},
        )

    monkeypatch.setattr(client, 'execute_agent_request', fake_execute_agent_request)
    req = AgentExecutionRequest(
        participant_id='p1',
        participant_name='generated step',
        participant_instruction='Provide a current source-backed answer.',
        task_name='Task',
        task_instruction='Task instruction',
        community_id='c1',
        shared_context={},
    )
    result = await client.execute_intermediate_step(req)
    assert called.get('used_primary_runtime') is True
    assert result.final_answer == 'verified current result'
    assert result.workflow_results['dataflow_step']['execution_mode'] == 'primary_runtime_standalone_step'


def test_preflight_defers_approval_control_fields_until_node_execution():
    service = AgentStudioService.__new__(AgentStudioService)
    class DummyDelegationRuntime:
        def _is_approval_parameter_field(self, field):
            return str(field.get('name') or field.get('field') or '').endswith('approval_confirmed')
    service.delegation_runtime = DummyDelegationRuntime()
    fields = [
        {'name': 'participant.approval_confirmed', 'required': True},
        {'name': 'ordinary_input', 'required': True},
    ]
    filtered = service._filter_deferred_execution_control_fields(fields)
    assert filtered == [{'name': 'ordinary_input', 'required': True}]
