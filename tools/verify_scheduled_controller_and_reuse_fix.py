from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from auxiliary_brain.storage import JsonStore
from auxiliary_brain.studio import AgentStudioService


async def main() -> None:
    source_runtime = Path('/mnt/data/archive_inspect')
    with TemporaryDirectory() as td:
        root = Path(td) / 'runtime'
        for rel in ['generated/tasks', 'generated/agents']:
            shutil.copytree(source_runtime / rel, root / rel, dirs_exist_ok=True)
        store = JsonStore(root=root)
        svc = AgentStudioService(store=store)
        called = {'reuse': False, 'participants': []}

        async def no_reuse(*args, **kwargs):
            called['reuse'] = True
            raise AssertionError('scheduled/control-plane payload execution must not use reusable artifact cache')

        async def fake_delegate(task_graph, participants):
            called['participants'] = [p.get('participant_id') or p.get('id') for p in participants]
            return {
                'run_id': 'test_run',
                'status': 'completed',
                'synthesis': {'final_answer': 'ok'},
            }

        svc._try_reused_task_execution = no_reuse  # type: ignore[method-assign]
        svc.delegation_runtime.execute_task = fake_delegate  # type: ignore[method-assign]
        result = await svc.execute_task('SendMailTask', provided_inputs={}, instruction='')
        task_graph = store.read_json('generated/tasks/SendMailTask.json')
        controllers = set((task_graph.get('schedule_policy') or {}).get('controller_participant_ids') or [])
        selected = set(task_graph.get('selected_participant_ids') or [])
        expected_payload = sorted(selected - controllers)
        assert result.get('status') == 'completed', result
        assert called['reuse'] is False, called
        assert sorted(called['participants']) == expected_payload, called
        assert controllers, 'test fixture must include control participants'
        assert expected_payload, 'test fixture must include payload participants'

if __name__ == '__main__':
    asyncio.run(main())
