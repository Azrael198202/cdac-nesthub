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
    """Generic config-driven workflow engine.

    It knows only workflow/node execution mechanics. Business content must be
    generated in runtime configs or tools, not hardcoded here.
    """

    def __init__(self) -> None:
        self.bootstrapper = RuntimeBootstrapper()
        self.config = RuntimeConfig()
        self.executor = NodeExecutor()
        self.store = FileStore()
        self.conversation = ConversationStore()

    async def run(self, user_input: str) -> AsyncGenerator[WorkflowEvent, None]:
        run_id = uuid.uuid4().hex[:12]
        self.conversation.append("user", user_input, {"run_id": run_id})
        async for ev in self._run_from(run_id=run_id, user_input=user_input, start_index=0, state=None, approval=None):
            yield ev

    async def resume(self, run_id: str, approved: bool, comment: str | None = None) -> AsyncGenerator[WorkflowEvent, None]:
        session = self._read_session(run_id)
        if not session:
            yield WorkflowEvent("error", "Session not found", f"No waiting session found for run_id={run_id}", "blocked")
            return
        approval = {"approved": approved, "comment": comment or "", "time": datetime.now(timezone.utc).isoformat()}
        state = session.get("state", {})
        state.setdefault("human_reviews", []).append({
            "node_id": session.get("waiting_node_id"),
            **approval,
        })
        if not approved:
            yield WorkflowEvent("human_rejected", "Human rejected checkpoint", comment or "The previous step was rejected.", "blocked")
            self._delete_session(run_id)
            self._write_trace(run_id, session.get("trace", []), state)
            return
        yield WorkflowEvent("human_approved", "Human approved checkpoint", comment or "Continuing workflow.", "completed", {
            "run_id": run_id,
            "node_id": session.get("waiting_node_id"),
        })
        async for ev in self._run_from(
            run_id=run_id,
            user_input=session.get("user_input", ""),
            start_index=int(session.get("next_index", 0)),
            state=state,
            approval=approval,
            trace=session.get("trace", []),
        ):
            yield ev

    async def _run_from(
        self,
        run_id: str,
        user_input: str,
        start_index: int,
        state: dict[str, Any] | None,
        approval: dict[str, Any] | None,
        trace: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[WorkflowEvent, None]:
        trace = trace or []
        if start_index == 0:
            status = self.bootstrapper.bootstrap()
            ev = WorkflowEvent("bootstrap", "Runtime bootstrap", status.message, "completed", {"run_id": run_id, **status.__dict__})
            trace.append(ev.to_dict()); yield ev

        workflow = self.config.workflow("base_orchestration")
        if not workflow:
            ev = WorkflowEvent("error", "Workflow missing", "runtime/configs/workflows/base_orchestration.yaml was not found", "blocked", {"run_id": run_id})
            trace.append(ev.to_dict()); yield ev; return

        if state is None:
            state = {"run_id": run_id, "user_input": user_input, "node_results": {}, "errors": {}, "human_reviews": []}
            ev = WorkflowEvent("workflow", "Workflow loaded", workflow.get("name", "unnamed"), "completed", {"run_id": run_id, "workflow": workflow})
            trace.append(ev.to_dict()); yield ev

        nodes = workflow.get("nodes", [])
        for idx in range(start_index, len(nodes)):
            node = nodes[idx]
            node_events: list[WorkflowEvent] = []
            async for event in self.executor.execute(node, state):
                if event.data is None:
                    event.data = {"run_id": run_id}
                elif isinstance(event.data, dict):
                    event.data.setdefault("run_id", run_id)
                node_events.append(event)
                trace.append(event.to_dict())

                if event.status == "blocked":
                    self._write_trace(run_id, trace, state)
                    self._delete_session(run_id)
                    yield event
                    return

                if event.status == "waiting":
                    self._write_session(run_id, {
                        "run_id": run_id,
                        "user_input": user_input,
                        "state": state,
                        "trace": trace,
                        "workflow_id": workflow.get("workflow_id", "base_orchestration"),
                        "waiting_node_id": node.get("id"),
                        "next_index": idx + 1,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    })
                    yield event
                    return

                yield event

        self._delete_session(run_id)
        self._write_trace(run_id, trace, state)

    def _session_path(self, run_id: str):
        return RUNTIME_DIR / f"sessions/{run_id}.json"

    def _read_session(self, run_id: str) -> dict[str, Any] | None:
        path = self._session_path(run_id)
        if not path.exists():
            return None
        return self.store.read_json(path, {})

    def _write_session(self, run_id: str, payload: dict[str, Any]) -> None:
        self.store.write_json(self._session_path(run_id), payload)

    def _delete_session(self, run_id: str) -> None:
        path = self._session_path(run_id)
        if path.exists():
            path.unlink()

    def _write_trace(self, run_id: str, trace: list[dict[str, Any]], state: dict[str, Any]) -> None:
        self.store.write_json(RUNTIME_DIR / f"traces/{run_id}.json", {
            "run_id": run_id,
            "time": datetime.now(timezone.utc).isoformat(),
            "trace": trace,
            "state": state,
        })
