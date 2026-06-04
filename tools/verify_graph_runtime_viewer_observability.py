from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_core.graph.graph_visualization import GraphVisualStateBuilder
from auxiliary_brain.studio import AgentStudioService


def main() -> None:
    root = Path('runtime')
    if root.exists():
        shutil.rmtree(root)
    service = AgentStudioService()
    service.store.ensure_workspace()
    task = {
        'graph_id': 'graph_observability_test',
        'task_name': 'TaskObservabilityTest',
        'status': 'created',
        'selected_participant_ids': ['participant_1'],
        'schedule_policy': {
            'enabled': True,
            'mode': 'recurring',
            'interval_seconds': 60,
            'next_run_at': '2026-01-01T00:00:00+00:00',
        },
        'tasks': [{
            'task_id': 'step_1',
            'participant_id': 'participant_1',
            'participant_display_name': 'Runtime Participant',
            'status': 'pending',
            'capability_profile': {
                'capability_type': 'runtime_registered_tool',
                'tool_id': 'generic_tool_fixture',
                'capability': 'generic_capability_fixture',
                'binding_status': 'bound',
            },
        }],
    }
    service.store.write_json('generated/tasks/TaskObservabilityTest.json', task)
    trace_dir = Path('runtime/traces/scheduled_tasks')
    trace_dir.mkdir(parents=True, exist_ok=True)
    with (trace_dir / 'scheduler.jsonl').open('w', encoding='utf-8') as fh:
        fh.write(json.dumps({'timestamp': '2026-01-01T00:00:00+00:00', 'event': 'dispatch_started', 'task_name': 'TaskObservabilityTest'}, ensure_ascii=False) + '\n')
        fh.write(json.dumps({'timestamp': '2026-01-01T00:00:01+00:00', 'event': 'dispatch_completed', 'task_name': 'TaskObservabilityTest'}, ensure_ascii=False) + '\n')

    snapshot = service.snapshot()
    state = GraphVisualStateBuilder().to_dict(GraphVisualStateBuilder().from_snapshot(snapshot, graph_id='graph_observability_test'))
    assert any(n.get('kind') == 'runtime_capability' and 'generic_tool_fixture' in n.get('id', '') for n in state['nodes']), state['nodes']
    assert any(e.get('label') == 'uses capability' for e in state['edges']), state['edges']

    paused = service.set_task_schedule_enabled('TaskObservabilityTest', False)
    assert paused['ok'] and paused['schedule_policy']['enabled'] is False, paused
    resumed = service.set_task_schedule_enabled('TaskObservabilityTest', True)
    assert resumed['ok'] and resumed['schedule_policy']['enabled'] is True, resumed
    history = service.task_execution_history('TaskObservabilityTest')
    events = {item.get('event') for item in history}
    assert {'dispatch_started', 'dispatch_completed', 'schedule_paused', 'schedule_resumed'} <= events, history
    print('graph runtime viewer observability verification passed')


if __name__ == '__main__':
    main()
