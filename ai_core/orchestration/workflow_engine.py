from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, AsyncGenerator
import uuid

from ai_core.runtime.bootstrap import RuntimeBootstrapper
from ai_core.runtime.runtime_config import RuntimeConfig
from ai_core.runtime.file_store import FileStore
from ai_core.runtime.paths import RUNTIME_DIR
from ai_core.orchestration.events import WorkflowEvent
from ai_core.orchestration.node_executor import NodeExecutor
from ai_core.memory.conversation_store import ConversationStore


class WorkflowEngine:
    def __init__(self) -> None:
        self.bootstrapper = RuntimeBootstrapper()
        self.config = RuntimeConfig()
        self.executor = NodeExecutor()
        self.store = FileStore()
        self.conversation = ConversationStore()

    async def run(self, user_input: str) -> AsyncGenerator[WorkflowEvent, None]:
        run_id = uuid.uuid4().hex[:12]
        trace: list[dict[str, Any]] = []
        status = self.bootstrapper.bootstrap()
        ev = WorkflowEvent("bootstrap", "Runtime bootstrap", status.message, "completed", status.__dict__)
        trace.append(ev.to_dict()); yield ev

        self.conversation.append("user", user_input, {"run_id": run_id})
        workflow = self.config.workflow("base_orchestration")
        if not workflow:
            ev = WorkflowEvent("error", "Workflow missing", "runtime/configs/workflows/base_orchestration.yaml was not found", "blocked")
            trace.append(ev.to_dict()); yield ev; return

        state: dict[str, Any] = {"run_id": run_id, "user_input": user_input, "node_results": {}, "errors": {}}
        ev = WorkflowEvent("workflow", "Workflow loaded", workflow.get("name", "unnamed"), "completed", workflow)
        trace.append(ev.to_dict()); yield ev

        for node in workflow.get("nodes", []):
            async for event in self.executor.execute(node, state):
                trace.append(event.to_dict())
                yield event
                if event.status == "blocked":
                    self._write_trace(run_id, trace, state)
                    return
        self._write_trace(run_id, trace, state)

    def _write_trace(self, run_id: str, trace: list[dict[str, Any]], state: dict[str, Any]) -> None:
        self.store.write_json(RUNTIME_DIR / f"traces/{run_id}.json", {
            "run_id": run_id,
            "time": datetime.now(timezone.utc).isoformat(),
            "trace": trace,
            "state": state,
        })
