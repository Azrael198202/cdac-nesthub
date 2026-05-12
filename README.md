# AI Core Config-Driven Node Runtime v18

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


## v18 Fix

- Updated UI version label from v18 to v18.
- Added `/api/version`.
- Added no-cache headers for `/`.
- This avoids confusion when the browser or an old server process displays stale UI text.


## v18 Fix

- Fixed JavaScript syntax errors in `apps/web/index.html`.
- `/api/chat` now returns `run_id` immediately.
- Workflow execution starts in a background task.
- UI now displays `POST /api/chat` errors and SSE connection status.
- Added `.vscode/launch.json` and `.vscode/tasks.json`.


## v18 Update

- Added `runtime/generated/adapters/*.yaml`.
- `LLMJsonExecutor` calls a real configured provider instead of returning a placeholder.
- Provider config is generated at `runtime/configs/models/providers.yaml`.
- Supported provider protocols:
  - Ollama `/api/chat`
  - OpenAI Chat Completions
- If no provider is available, the workflow shows a clear `Node execution failed` message.
- `ai_core` still has no domain/task/business logic.


## v18 Update

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


## v18 Update

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


## v18 Fix

- Rewrites `RuntimeBootstrap` to always create:
  - `runtime/configs/models/providers.yaml`
  - `runtime/generated/adapters/*.yaml`
  - `runtime/generated/nodes/*.yaml`
  - `runtime/generated/prompts/*.yaml`
  - `runtime/generated/schemas/*.json`
- Adds Ollama auto-start attempt before model pull.
- Existing old `runtime/` directories should be deleted once when upgrading:

```bash
rm -rf runtime
python main.py
```


## v18 Update

### Fix: Ollama command not found

When the Ollama service is running but the command `ollama` is not in the current PATH, runtime now resolves common executable locations before running:

```bash
ollama pull <model>
```

On Windows it may rewrite it to:

```text
"C:\Users\...\AppData\Local\Programs\Ollama\ollama.exe" pull qwen3:4b
```

### Runtime Learning

When the user clicks `Modify JSON & Continue`, runtime records:

```text
original_output
modified_output
feedback
node_id
user_input
```

Into:

```text
runtime/datasets/corrections.jsonl
runtime/knowledge/prompt_optimization_memory.jsonl
```

### Correction Memory Retrieval

For future similar tasks, the executor retrieves correction memory and injects it into the prompt.


## v18 Update

### Provider Handler Registry

`provider_router.py` no longer hardcodes `if ollama / elif openai`.

It now dispatches by `provider.type`:

```text
ProviderRouter
↓
ProviderHandlerRegistry
↓
ProviderHandler
```

Supported provider types:

```text
ollama
openai
openai_compatible
```

`openai_compatible` can be used for:

```text
vLLM
LM Studio
LocalAI
LiteLLM proxy
Any /v18/chat/completions compatible service
```

### Ollama Pull Failure Details

When `ollama pull` fails, stdout and stderr are collected and included in the final error.

### Fallback Models

`runtime/configs/models/providers.yaml` supports:

```yaml
fallback_models:
  - qwen2.5:3b
  - qwen3:1.7b
  - llama3.2:3b
```

If primary model pull fails, runtime automatically tries fallback models.


## v18 Update

### Ollama endpoint strategy

Some local Ollama-compatible services support `/api/tags` and `/api/generate` but return 404 on `/api/chat`.

The Ollama handler now supports:

```yaml
endpoint_strategy: auto
chat_endpoint: /api/chat
generate_endpoint: /api/generate
```

Behavior:

```text
POST /api/chat
↓
if 404
↓
fallback to POST /api/generate
```

`/api/chat` reads content from:

```text
message.content
```

`/api/generate` reads content from:

```text
response
```


## v18 Update

Provider Auto Installer is added.

Runtime flow:

```text
resolve provider binary
↓
if missing, install by OS-specific command from runtime config
↓
resolve binary again
↓
start provider as daemon
↓
poll /api/tags until ready
↓
pull model / fallback models
↓
call inference endpoint
```

Ollama provider now supports:

```yaml
binary: ollama
auto_install: true
install:
  windows:
    - winget install Ollama.Ollama --accept-source-agreements --accept-package-agreements --disable-interactivity
  macos:
    - brew install ollama
  linux:
    - curl -fsSL https://ollama.com/install.sh | sh
executable_hints:
  windows:
    - "%LOCALAPPDATA%\\Programs\\Ollama\\ollama.exe"
    - "%ProgramFiles%\\Ollama\\ollama.exe"
start_command: "{binary} serve"
pull_command: "{binary} pull {model}"
```


## v18 Update

### UI single-run lock

The chat input and Send button are disabled while a workflow is running.

Disabled during:

```text
provider installation
provider start
model pull
LLM request
workflow execution
```

Re-enabled after:

```text
RUN_COMPLETED
RUN_FAILED
RUN_CANCELLED
SSE error
```

Human Review and API Key input use their own buttons, so the main Send button stays locked.


## v18 Update

### Runtime Learning + Runtime Template Evolution

This version fixes the issue where `Reject & Retry` feedback such as:

```text
tasks should be structured objects instead of string array.
Need task_id/task_type/action/parameters.
Booking actions require human confirmation.
Need more missing_information fields.
```

was not strong enough to change the next model output.

New behavior:

```text
Reject & Retry
↓
record reject feedback
↓
evolve runtime/generated prompt/schema for the current node
↓
retry the same node
```

The generated schema can automatically evolve from:

```json
"tasks": {"type": "array"}
```

to:

```json
"tasks": {
  "type": "array",
  "items": {
    "type": "object",
    "required": ["task_id", "task_type", "action", "parameters"]
  }
}
```

### Modify JSON & Continue Learning

When the user clicks `Modify JSON & Continue`, runtime records:

```text
original_output
modified_output
human_corrected_output
feedback
node_id
user_input
```

Into:

```text
runtime/datasets/corrections.jsonl
runtime/knowledge/prompt_optimization_memory.jsonl
```

### Correction Memory Retrieval

Future similar tasks retrieve correction memory and inject it into prompts before model execution.

### Applies to known and unknown nodes

`RuntimeTemplateGenerator` works for any node_id. Known nodes get better default contracts; unknown nodes get generic prompt/schema and can evolve from human feedback.


## v18 Update

### Recoverable JSON Schema Validation

Schema validation failure no longer terminates the workflow.

```text
LLM JSON generated
↓
schema validation failed
↓
checkpoint current state
↓
show validation error and generated JSON
↓
Human can Reject & Retry or Modify JSON & Continue
```

Reject & Retry combines the human feedback with the validation error, then evolves the current node's runtime-generated prompt/schema and retries the same node.

Example: if `requires_human_review` is an object but schema expects boolean, runtime can evolve the schema to support a compatible human_review structure.


## v18 Update

### Hierarchical Collapsible Workflow UI

The UI now groups execution events by logical node instead of showing every event as a flat card.

Display structure:

```text
Run
 ├─ runtime
 ├─ input_parsing
 │   ├─ capability check
 │   ├─ provider route
 │   ├─ model request
 │   ├─ validation
 │   └─ human review
 ├─ intent_recognition
 │   ├─ correction memory
 │   ├─ prompt rendering
 │   ├─ provider route
 │   └─ validation
 └─ ...
```

Each node is a collapsible card. Internal steps are displayed as a timeline.

This makes long-running operations such as installation, model pull, LLM inference, validation, and human review easier to follow.
