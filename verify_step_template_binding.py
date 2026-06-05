from auxiliary_brain.delegation.delegation_runtime import AgentDelegationRuntime
from ai_core.agent_delegation import AgentExecutionResult

runtime = AgentDelegationRuntime()
participant = {
    'participant_id': 'send_participant',
    'display_name': 'Send Agent',
    'runtime_parameters': {'body': '{{Step3.final_answer}}'},
    'parameter_contract': {'parameters': [], 'missing_information': []},
}
completed = [
    AgentExecutionResult(participant_id='controller', participant_name='Controller Agent', core_run_id='r0', status='completed', final_answer='scheduled', workflow_results={'final_answer':'scheduled'}, origin='test'),
    AgentExecutionResult(participant_id='weather_participant', participant_name='Weather Agent', core_run_id='r1', status='completed', final_answer='weather material', workflow_results={'final_answer':'weather material'}, origin='test'),
    AgentExecutionResult(participant_id='extract_participant', participant_name='Extract final answer', core_run_id='r2', status='completed', final_answer='weather material', workflow_results={'final_answer':'weather material'}, origin='test'),
]
task_graph = {
    'tasks': [
        {'participant_id':'controller','participant_display_name':'Controller Agent','source_step_id':'step_1'},
        {'participant_id':'weather_participant','participant_display_name':'Weather Agent','source_step_id':'step_2'},
        {'participant_id':'extract_participant','participant_display_name':'Extract final answer','source_step_id':'step_3'},
        {'participant_id':'send_participant','participant_display_name':'Send Agent','source_step_id':'step_4'},
    ]
}
runtime._resolve_task_variable_placeholders_for_participant(
    participant=participant,
    completed_results=completed,
    dependency_plan={},
    task_graph=task_graph,
)
assert participant['runtime_parameters']['body'] == 'weather material', participant
print('step template binding verification passed')
