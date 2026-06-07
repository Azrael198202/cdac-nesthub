from pathlib import Path
import json
import tempfile
import asyncio

from ai_core.runtime.scheduler.scheduled_task_runner import ScheduledTaskRunner

async def main():
    with tempfile.TemporaryDirectory() as td:
        base=Path(td)
        tasks=base/'runtime'/'generated'/'tasks'
        traces=base/'runtime'/'traces'/'scheduled_tasks'
        tasks.mkdir(parents=True)
        (tasks/'SendMailTask.json').write_text(json.dumps({
            'task_name':'SendMailTask',
            'selected_participant_ids':['controller','payload'],
            'schedule_policy':{
                'enabled':True,
                'mode':'recurring',
                'interval_seconds':60,
                'next_run_at':'2000-01-01T00:00:00+00:00',
                'controller_participant_ids':['controller'],
            },
            'tasks':[{'participant_id':'controller'}, {'participant_id':'payload'}]
        }), encoding='utf-8')
        seen={}
        async def executor(task_name, task_graph):
            policy=task_graph.get('schedule_policy') or {}
            controllers=set(policy.get('controller_participant_ids') or [])
            selected=task_graph.get('selected_participant_ids') or []
            payload=[x for x in selected if x not in controllers]
            seen['payload']=payload
            return {'status':'completed','run_id':'test'}
        runner=ScheduledTaskRunner(tasks_dir=tasks, trace_dir=traces)
        await runner.run_once(executor)
        assert seen['payload']==['payload'], seen
        log=(traces/'scheduler.jsonl').read_text(encoding='utf-8')
        assert '"event": "dispatch_started"' in log
        assert 'skipped_controller_participants' in log
        print('scheduled payload dispatch fix2 verified')

asyncio.run(main())
