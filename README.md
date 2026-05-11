# AI Core Config-Driven Node Runtime v4

This version enforces the rule that `ai_core` must not contain business/domain/task-specific logic.

## Key Principle

```text
ai_core = interpreter / executor
runtime/generated = generated brain logic
```

## What changed

- `ai_core/nodes/node_runner.py` is only a generic entry point.
- Node behavior is loaded from `runtime/generated/nodes/*.yaml`.
- Prompts are loaded from `runtime/generated/prompts/*.yaml`.
- Output schemas are loaded from `runtime/generated/schemas/*.json`.
- Execution is delegated to generic executors: `llm_json`, `tool_call`, `workflow_call`, `mcp_call`, `human_review`, `python_plugin`, `static_transform`.
- No fixed input parsing, intent analysis, workflow planning, weather, flight, booking, SDLC, family, expense, or domain logic exists inside `ai_core`.

## Run

```bash
pip install -r requirements.txt
python main.py
```

Open:

```text
http://127.0.0.1:8000
```

## Smoke test

```bash
python scripts/smoke_test.py
```


## v4 Fix

`/api/chat` now returns `run_id` immediately and starts workflow execution in the background.

Before:

```text
POST /api/chat waits until the workflow reaches a checkpoint
↓
UI cannot connect to SSE immediately
↓
Looks like no response
```

Now:

```text
POST /api/chat returns run_id immediately
↓
UI connects to /api/events/{run_id}
↓
Workflow runs in background
↓
Events stream to the chat area and workflow panel
```
