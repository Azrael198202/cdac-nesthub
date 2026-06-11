from dataclasses import dataclass

from auxiliary_brain.delegation.workflow_output_resolver import WorkflowOutputResolver


@dataclass
class Result:
    participant_id: str
    participant_name: str
    status: str
    final_answer: str
    workflow_results: dict


def test_resolves_arbitrary_step_number_and_public_field():
    resolver = WorkflowOutputResolver()
    results = [
        Result('a', 'first', 'completed', 'first public result', {}),
        Result('b', 'second', 'completed', 'second public result', {'final_synthesis': {'final_answer': 'second synthesis result'}}),
        Result('c', 'third', 'completed', '', {'final_synthesis': {'final_answer': 'third synthesis result'}}),
    ]
    refs = resolver.build_reference_map(completed_results=results, dependency_ids=set(), task_graph={'tasks': [
        {'participant_id': 'a', 'source_step_id': 'step_1'},
        {'participant_id': 'b', 'source_step_id': 'step_2'},
        {'participant_id': 'c', 'source_step_id': 'step_3'},
    ]})
    resolved = resolver.resolve({'body': '{{Step 3.final_answer}}'}, refs)
    assert resolved.unresolved == []
    assert resolved.value['body'] == 'third synthesis result'


def test_rejects_internal_placeholder_as_exportable_output():
    resolver = WorkflowOutputResolver()
    results = [
        Result('a', 'first', 'completed', 'The primary runtime completed without a user-facing final answer. Intermediate node data was intentionally not exposed.', {}),
    ]
    refs = resolver.build_reference_map(completed_results=results, dependency_ids=set(), task_graph=None)
    resolved = resolver.resolve('{{Step1.final_answer}}', refs)
    assert resolved.value == '{{Step1.final_answer}}'
    assert resolved.unresolved and resolved.unresolved[0]['reference'] == 'Step1.final_answer'


def test_resolves_named_step_field_without_fixed_step_one():
    resolver = WorkflowOutputResolver()
    results = [Result('producer_id', 'Producer Node', 'completed', '', {'output': {'content': 'named public material'}})]
    refs = resolver.build_reference_map(completed_results=results, dependency_ids=set(), task_graph={'tasks': [{'participant_id': 'producer_id', 'task_id': 'producer_task'}]})
    resolved = resolver.resolve('prefix {{producer_task.content}} suffix', refs)
    assert resolved.unresolved == []
    assert resolved.value == 'prefix named public material suffix'


def test_executable_input_can_resolve_from_explicit_step_alias_when_dependency_metadata_is_missing():
    from auxiliary_brain.delegation.delegation_runtime import AgentDelegationRuntime

    resolver_runtime = AgentDelegationRuntime.__new__(AgentDelegationRuntime)
    resolver_runtime.workflow_output_resolver = WorkflowOutputResolver()
    resolver_runtime._participant_dependency_ids = lambda participant, dependency_plan: ['consumer']
    resolver_runtime._task_variable_reference_map = AgentDelegationRuntime._task_variable_reference_map.__get__(resolver_runtime, AgentDelegationRuntime)
    resolver_runtime._collect_unresolved_task_templates = AgentDelegationRuntime._collect_unresolved_task_templates.__get__(resolver_runtime, AgentDelegationRuntime)
    resolver_runtime._resolve_executable_input_templates = AgentDelegationRuntime._resolve_executable_input_templates.__get__(resolver_runtime, AgentDelegationRuntime)

    results = [Result('producer', 'Producer', 'completed', 'public material for downstream', {})]
    resolved, unresolved, debug = resolver_runtime._resolve_executable_input_templates(
        input_data={'body': '{{Step1.final_answer}}'},
        participant={'participant_id': 'consumer'},
        completed_results=results,
        dependency_plan={},
        task_graph={'tasks': [{'participant_id': 'producer', 'source_step_id': 'step_1'}, {'participant_id': 'consumer', 'source_step_id': 'step_2'}]},
    )
    assert unresolved == []
    assert resolved['body'] == 'public material for downstream'
    assert any(item['scope'] == 'explicit_step_aliases' for item in debug)
