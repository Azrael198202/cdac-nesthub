from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from verification_brain import RuntimeVerificationBrain, RuntimeVerificationFoundation


def main() -> None:
    unique = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')
    run_id = f'v21_test_run_{unique}'
    task_name = f'V21SideEffectTest_{unique}'
    runtime = Path('runtime')
    # Do not delete all runtime data in normal use. This verifier only removes
    # its own generated confirmation/report files when run in a clean package.
    (runtime / 'generated').mkdir(parents=True, exist_ok=True)

    verifier = RuntimeVerificationBrain()
    output = {
        'run_payload': {
            'status': 'completed',
            'run_id': run_id,
            'task_name': task_name,
            'agent_results': [{
                'participant_id': 'participant_A',
                'participant_name': 'Participant A',
                'status': 'completed',
                'workflow_results': {
                    'status': 'completed',
                    'tool_id': 'generic_runtime_tool',
                    'capability_type': 'runtime_registered_tool',
                    'side_effect': True,
                },
            }],
        },
        'task_graph': {'task_name': task_name, 'graph_id': 'v21_graph'},
        'participants': [{'participant_id': 'participant_A'}],
    }
    result = verifier.verify(output=output)
    side_checks = [c for c in result.checks if c.get('level') == 6]
    assert any(c.get('side_effect_status') == 'accepted_pending_user_confirmation' for c in side_checks), side_checks
    assert result.passed is True, result.to_dict()

    foundation = RuntimeVerificationFoundation()
    report = foundation.inspect_run(
        task_graph=output['task_graph'],
        participants=output['participants'],
        run_payload=output['run_payload'],
        stage='v21_verifier_test',
    )
    assert report is None, report.to_dict() if report else None
    confirmations = foundation.list_side_effect_confirmations(limit=50)
    confirmation = None
    for item in confirmations:
        if item.get('run_id') == run_id and item.get('participant_id') == 'participant_A':
            confirmation = item
            break
    assert confirmation, confirmations
    assert confirmation['status'] == 'pending_user_feedback_default_success'

    feedback = foundation.record_user_side_effect_feedback(
        confirmation_id=confirmation['confirmation_id'],
        outcome='failed',
        note='Synthetic user confirmation that the external side effect did not work.',
    )
    assert feedback.get('ok') is True, feedback
    assert feedback.get('failure_report', {}).get('failure_class') == 'user_confirmed_side_effect_failure', feedback
    print(json.dumps({'ok': True, 'confirmation_id': confirmation['confirmation_id']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
