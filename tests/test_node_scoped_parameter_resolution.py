import asyncio

from auxiliary_brain.delegation.delegation_runtime import AgentDelegationRuntime


def test_studio_preflight_does_not_collect_participant_profile_fields():
    from pathlib import Path
    source = Path('auxiliary_brain/studio/service.py').read_text(encoding='utf-8')
    helper_start = source.index('def _build_preflight_resolution_context')
    helper_body = source[helper_start:source.index('def _collect_bound_resource_refs', helper_start)]
    assert 'agent_fields=[]' in helper_body
    assert '_preflight_uploaded_artifact_parameters' in helper_body


def test_node_scoped_parameter_fields_include_runtime_generated_profile_fields():
    runtime = AgentDelegationRuntime()
    participant = {
        'participant_id': 'p1',
        'display_name': 'Generic Participant',
        'parameter_contract': {
            'source': 'runtime_llm',
            'parameters': [
                {'name': 'user_timezone', 'required': True, 'values': []},
                {'name': 'message', 'required': True, 'values': []},
            ],
        },
        'runtime_parameters': {},
    }
    fields = runtime._collect_node_parameter_fields(participant)
    assert [field['parameter_name'] for field in fields] == ['user_timezone', 'message']


def test_node_scoped_parameter_fields_skip_uploaded_artifact_participants():
    runtime = AgentDelegationRuntime()
    participant = {
        'participant_id': 'p1',
        'display_name': 'Generic Participant',
        'uploaded_artifacts': [{'artifact_id': 'a1'}],
        'parameter_contract': {
            'source': 'runtime_llm',
            'parameters': [{'name': 'value', 'required': True, 'values': []}],
        },
    }
    assert runtime._collect_node_parameter_fields(participant) == []


def test_node_parameter_pause_keeps_completed_results_and_current_participant():
    runtime = AgentDelegationRuntime()
    payload = {'run_id': 'run1', 'progress_events': [], 'agent_results': [{'participant_id': 'done', 'status': 'completed'}]}
    paused = runtime._pause_for_node_parameters(
        run_payload=payload,
        run_id='run1',
        participant={'participant_id': 'p2'},
        participant_index=2,
        participant_name='Second Participant',
        missing_fields=[{'field': 'p2.value', 'name': 'p2.value'}],
        runtime_parameters={},
    )
    assert paused['status'] == 'requires_input'
    assert paused['current_stage'] == 'participant_2_waiting_parameters'
    assert paused['pending_action']['kind'] == 'agent_node_parameter_collection'
    assert paused['pending_action']['participant_id'] == 'p2'
    assert paused['agent_results'][0]['participant_id'] == 'done'
