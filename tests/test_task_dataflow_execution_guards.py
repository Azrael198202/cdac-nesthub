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


def test_composite_task_parameters_do_not_pollute_upstream_step_context():
    service = AgentStudioService.__new__(AgentStudioService)
    instruction = '''Create a task named AnyTask.

Step 1:
Please produce current public information.

Step 2:
Call Any Agent.
Parameters for Any Agent:
- target: example@example.com
- body: {{Step1.final_answer}}
'''
    top = service._extract_top_level_runtime_parameters_from_instruction(instruction)
    assert 'target' not in top
    assert 'body' not in top

    tasks = [
        {'participant_id': 'source', 'source_instruction_fragment': 'Please produce current public information.'},
        {'participant_id': 'consumer', 'participant_display_name': 'Any Agent', 'source_instruction_fragment': 'Call Any Agent.\nParameters for Any Agent:\n- target: example@example.com\n- body: {{Step1.final_answer}}'},
    ]
    scoped = service._extract_step_scoped_runtime_parameters_from_tasks(tasks)
    assert scoped['consumer.target'] == 'example@example.com'
    assert scoped['consumer.body'] == '{{Step1.final_answer}}'
    assert 'target' not in scoped
    assert 'body' not in scoped


@pytest.mark.asyncio
async def test_registered_tool_step_is_executed_directly_after_dependency_binding(monkeypatch):
    from auxiliary_brain.delegation.delegation_runtime import AgentDelegationRuntime

    runtime = AgentDelegationRuntime.__new__(AgentDelegationRuntime)
    runtime.workflow_output_resolver = None
    runtime.store = type('S', (), {'write_json': lambda self, path, payload: path})()
    runtime._fresh_task_participants = lambda selected: selected
    runtime._select_participants = lambda task_graph, participants: participants
    runtime._hydrate_runtime_bindings_for_task = lambda task_graph, selected: selected
    runtime._task_source_material = lambda task_graph, fallback_values: ''
    runtime._extract_structural_values_from_material = lambda source: {}
    runtime._build_task_mind_graph = lambda task_graph, selected: {'agent_relation_analysis': {'participants': {'source': {'depends_on': []}, 'tool': {'depends_on': ['source']}}}}
    runtime._build_participant_dependency_plan = lambda task_graph, selected: {'participants': {'source': {'depends_on': []}, 'tool': {'depends_on': ['source']}}}
    runtime._record_progress = lambda *args, **kwargs: None
    runtime._record_global_mind_graph_progress = lambda *args, **kwargs: None
    runtime._apply_task_runtime_parameters_to_selected = lambda selected, runtime_parameters: None
    runtime._collect_missing_agent_parameter_fields = lambda selected, dependency_plan=None: []
    runtime._participants_in_mind_graph_order = lambda selected, task_mind_graph: selected
    runtime._blocked_dependency_ids = lambda participant_id, completed_results, dependency_plan: []
    runtime._bind_dependency_outputs_to_participant = lambda participant, completed_results, dependency_plan: None
    runtime._build_participant_shared_context = lambda **kwargs: {}
    runtime._build_primary_runtime_progress_bridge = lambda *args, **kwargs: None
    runtime._sanitize_result_payload = lambda payload: payload
    runtime._now = lambda: 'now'
    runtime._collect_generated_files = lambda results: []
    runtime._terminal_results_for_synthesis = lambda results, task_mind_graph: results

    calls = {'primary': 0, 'tool': 0}

    async def primary(request, progress_callback=None):
        calls['primary'] += 1
        return AgentExecutionResult('source', 'Source', 'core1', 'completed', 'public material', {'final_synthesis': {'final_answer': 'public material'}})

    async def tool(participant, completed_results, dependency_plan, task_name):
        if not (participant.get('capability_profile') or {}).get('tool_id'):
            return None
        calls['tool'] += 1
        return AgentExecutionResult('tool', 'Tool', 'core2', 'completed', 'tool completed', {'tool_execution': {'status': 'completed'}})

    runtime._execute_workflow_step_through_ai_core_with_progress = primary
    runtime._try_execute_generated_capability = tool
    class PrimaryStub:
        async def synthesize_delegated_results(self, **kwargs):
            return {'status': 'completed', 'final_answer': 'done'}
    runtime.primary_client = PrimaryStub()

    task_graph = {'task_name': 'Task', 'instruction': 'Step 1:\nSource\nStep 2:\nCall tool', 'runtime_parameters': {}}
    participants = [
        {'participant_id': 'source', 'display_name': 'Source', 'execution_objective': 'Source'},
        {'participant_id': 'tool', 'display_name': 'Tool', 'execution_objective': 'Call tool', 'capability_profile': {'tool_id': 'registered_tool'}},
    ]
    result = await runtime._execute_task_with_selected(task_graph, participants)
    assert calls == {'primary': 1, 'tool': 1}
    assert result['status'] == 'completed'
