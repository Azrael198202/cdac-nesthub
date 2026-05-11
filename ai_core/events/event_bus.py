import asyncio
import json
from typing import Dict, Any, AsyncGenerator


class EventBus:
    def __init__(self) -> None:
        self._queues: Dict[str, asyncio.Queue] = {}

    def queue(self, run_id: str) -> asyncio.Queue:
        if run_id not in self._queues:
            self._queues[run_id] = asyncio.Queue()
        return self._queues[run_id]

    async def emit(self, run_id: str, event: Dict[str, Any]) -> None:
        event.setdefault("run_id", run_id)
        await self.queue(run_id).put(event)

    async def stream(self, run_id: str) -> AsyncGenerator[str, None]:
        q = self.queue(run_id)
        while True:
            event = await q.get()
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            if event.get("type") in {"RUN_COMPLETED", "RUN_FAILED", "RUN_CANCELLED"}:
                break


event_bus = EventBus()
