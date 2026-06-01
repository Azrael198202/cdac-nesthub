# v16.1.7 Async Run Terminal Progress

## What changed

- Agent Studio message execution now returns immediately with a UI run id.
- Long-running runtime work runs in a retained background task, not inside the request/response wait path.
- The UI polls `/api/agent-studio/run-status/{run_id}` and shows progressive lifecycle lines.
- Final answer rendering is allowed only after a terminal run status.
- Terminal statuses include `completed`, `failed`, `cancelled`, `blocked`, `requires_input`, and `pending_review`.
- The `running` indicator is cleared when the run reaches a terminal state.
- A heartbeat updates long execution status while model/tool work is still running.
- The page remains navigable while a model/tool workflow is executing.

## Boundary

This change is observability and state-management only. It does not add domain-specific capability logic to `ai_core`.
