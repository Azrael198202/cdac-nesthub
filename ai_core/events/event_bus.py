import asyncio
from typing import Dict, Any, AsyncGenerator

from ai_core.utils.safe_json import make_json_safe, safe_json_dumps


class EventBus:
    def __init__(self):
        self._queues: Dict[str, asyncio.Queue] = {}

    def queue(self, run_id: str) -> asyncio.Queue:
        if run_id not in self._queues:
            self._queues[run_id] = asyncio.Queue()
        return self._queues[run_id]

    async def emit(self, run_id: str, event: Dict[str, Any]) -> None:
        safe_event = make_json_safe(event)
        if isinstance(safe_event, dict):
            safe_event.setdefault('run_id', run_id)
        else:
            safe_event = {'run_id': run_id, 'type': 'EVENT_SERIALIZATION_REPAIRED', 'result': safe_event}
        await self.queue(run_id).put(safe_event)

    async def stream(self, run_id: str) -> AsyncGenerator[str, None]:
        q = self.queue(run_id)
        while True:
            event = await q.get()
            yield f"data: {safe_json_dumps(event)}\n\n"
            if isinstance(event, dict) and event.get('type') in {'RUN_COMPLETED', 'RUN_FAILED', 'RUN_CANCELLED'}:
                break


event_bus = EventBus()
