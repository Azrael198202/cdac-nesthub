from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from presentation_brain.failure_message_renderer import FailureMessageRenderer

report = {
    'failure_class': 'task_graph_static_validation_failed',
    'stage': 'create_task_graph',
    'task_name': 'ExampleTask',
    'graph_id': 'graph_test',
    'failed_checks': [
        {
            'level': 'create_task_graph',
            'check': 'declared_participant_reference_resolves',
            'failure_class': 'agent_reference_ambiguous',
            'message': 'A declared participant reference did not resolve to an existing durable participant.',
            'reference': 'SendMail Agent',
            'line': 9,
            'suggestions': ['SendGmail Agent'],
        },
        {
            'level': 'create_task_graph',
            'check': 'template_step_reference_exists',
            'failure_class': 'template_reference_not_found',
            'message': 'A template reference points to a step that is not declared in this task instruction.',
            'reference': '{{Step99.final_answer}}',
            'root': 'Step99',
            'declared_steps': ['step1', 'step2'],
        },
        {
            'level': 'create_task_graph',
            'check': 'template_step_reference_exists',
            'failure_class': 'template_reference_not_found',
            'message': 'A template reference points to a step that is not declared in this task instruction.',
            'reference': '{{Step99.final_answer}}',
            'root': 'Step99',
            'declared_steps': ['step1', 'step2'],
        },
    ],
}
message = FailureMessageRenderer().render(report, allow_llm=False).to_dict()
text = '\n'.join([message.get('title',''), message.get('summary',''), '\n'.join(message.get('reasons', [])), '\n'.join(message.get('suggestions', []))])
assert 'Task graph creation failed' in text
assert 'SendMail Agent' in text
assert 'SendGmail Agent' in text
assert '{{Step99.final_answer}}' in text
assert text.count('{{Step99.final_answer}}') == 1
print('verify_v22_1_static_validation_presentation_surface: passed')
