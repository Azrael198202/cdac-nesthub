# AI Core Config-Driven Node Runtime v9

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


## v9 Fix

- Updated UI version label from v3 to v9.
- Added `/api/version`.
- Added no-cache headers for `/`.
- This avoids confusion when the browser or an old server process displays stale UI text.


## v9 Fix

- Fixed JavaScript syntax errors in `apps/web/index.html`.
- `/api/chat` now returns `run_id` immediately.
- Workflow execution starts in a background task.
- UI now displays `POST /api/chat` errors and SSE connection status.
- Added `.vscode/launch.json` and `.vscode/tasks.json`.


## v9 Update

- Added `runtime/generated/adapters/*.yaml`.
- `LLMJsonExecutor` calls a real configured provider instead of returning a placeholder.
- Provider config is generated at `runtime/configs/models/providers.yaml`.
- Supported provider protocols:
  - Ollama `/api/chat`
  - OpenAI Chat Completions
- If no provider is available, the workflow shows a clear `Node execution failed` message.
- `ai_core` still has no domain/task/business logic.


## v9 Update

Adds visible execution status for model calls.

New event types:

```text
LLM_EXECUTOR_READY
LLM_PROMPT_RENDERED
LLM_ROUTE_START
LLM_HEALTH_CHECK
LLM_HEALTH_OK
LLM_PROVIDER_START
LLM_REQUEST_SENT
LLM_RESPONSE_RECEIVED
LLM_PROVIDER_DONE
LLM_PROVIDER_ERROR
LLM_JSON_VALIDATING
LLM_JSON_VALIDATED
```

The UI now shows:

```text
Calling LLM provider...
Elapsed: Ns
Completed / Failed
```

This makes it clear whether the backend is still waiting for the model, checking health, parsing JSON, or failed.


## v9 Update

Adds provider setup automation.

### Ollama

If Ollama is reachable but the configured model is missing, runtime automatically runs:

```bash
ollama pull <model>
```

Command output is streamed to the UI.

### External API Key

If OpenAI API key is missing, the UI shows an API key input form.

The key is saved to:

```text
runtime/configs/secrets/secrets.json
```

For production, replace the file-based secret store with OS Keychain, Vault, or a cloud secret manager.
