import pytest

from ai_core.agent_delegation.primary_brain_client import AgentExecutionRequest, AgentExecutionResult, PrimaryBrainDelegationClient
from auxiliary_brain.studio.service import AgentStudioService


@pytest.mark.asyncio
async def test_standalone_generated_step_uses_plain_primary_runtime_not_internal_envelope(monkeypatch):
    client = PrimaryBrainDelegationClient()
    called = {}

    async def fake_plain_primary_runtime_step(request, progress_callback=None):
        called['message'] = client._standalone_step_message(request)
        return AgentExecutionResult(
            participant_id=request.participant_id,
            participant_name=request.participant_name,
            core_run_id='core_primary',
            status='completed',
            final_answer='verified current result',
            workflow_results={'execution': {'status': 'completed'}},
        )

    monkeypatch.setattr(client, '_execute_plain_primary_runtime_step', fake_plain_primary_runtime_step)
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
    assert called.get('message') == 'Provide a current source-backed answer.'
    assert not called.get('message', '').startswith('AGENT_REQUEST=')
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


def test_extract_exportable_answer_from_nested_primary_results():
    client = PrimaryBrainDelegationClient()
    results = {
        'execution': {'status': 'blocked'},
        'final_synthesis': {'status': 'completed', 'final_answer': 'public result material'},
    }
    assert client._extract_exportable_answer_from_results(results) == 'public result material'


def test_primary_runtime_does_not_export_initialization_message():
    client = PrimaryBrainDelegationClient()
    state = {
        'status': 'completed',
        'results': {
            'input_parsing': {
                'status': 'initializing',
                'message': 'Workflow initialized for source collection.',
            },
            'final_synthesis': {
                'status': 'completed',
                'final_answer': 'The workflow is blocked and did not execute a tool yet. Please review the blocked step details.',
            },
        },
    }
    assert client._extract_final_answer(state) == ''
    assert client._extract_exportable_answer_from_results(state['results']) == ''


def test_workflow_output_resolver_ignores_nonterminal_initialization_message():
    from auxiliary_brain.delegation.workflow_output_resolver import WorkflowOutputResolver
    from ai_core.agent_delegation.primary_brain_client import AgentExecutionResult

    resolver = WorkflowOutputResolver()
    result = AgentExecutionResult(
        participant_id='p1',
        participant_name='source step',
        core_run_id='core1',
        status='completed',
        final_answer='',
        workflow_results={
            'input_parsing': {'status': 'initializing', 'message': 'Workflow initialized for source collection.'},
            'final_synthesis': {'status': 'completed', 'final_answer': 'The workflow is blocked and did not execute a tool yet. Please review the blocked step details.'},
        },
    )
    refs = resolver.build_reference_map(completed_results=[result], dependency_ids=set(), task_graph=None)
    assert not refs


def test_primary_runtime_does_not_export_pipeline_node_label():
    client = PrimaryBrainDelegationClient()
    assert not client._answer_has_result_material('input_parsing')
    assert client._extract_exportable_answer_from_results({'dataflow_step': {'status': 'completed', 'final_answer': 'input_parsing', 'exportable': True}}) == ''


def test_workflow_output_resolver_does_not_export_pipeline_node_label():
    from auxiliary_brain.delegation.workflow_output_resolver import WorkflowOutputResolver

    resolver = WorkflowOutputResolver()
    result = AgentExecutionResult(
        participant_id='p1',
        participant_name='source step',
        core_run_id='core1',
        status='completed',
        final_answer='input_parsing',
        workflow_results={'dataflow_step': {'status': 'completed', 'final_answer': 'input_parsing', 'exportable': True}},
    )
    refs = resolver.build_reference_map(completed_results=[result], dependency_ids=set(), task_graph=None)
    assert not refs
