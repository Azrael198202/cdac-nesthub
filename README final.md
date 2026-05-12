# AI Core Dynamic Capability Runtime v1

## Overview

AI Core Dynamic Capability Runtime v1 is a self-evolving orchestration runtime designed to execute complex AI workflows without hardcoding business logic, providers, or tools inside the core engine.

Unlike traditional AI systems where:

```text
Core knows Ollama
Core knows Docker
Core knows Playwright
Core knows PostgreSQL
```

this architecture introduces a **Dynamic Capability System**.

The core runtime only understands:

```text
Capabilities
Workflow Nodes
Approvals
Execution
Learning
```

Everything else is dynamically generated, installed, verified, registered, and evolved at runtime.

---

# Core Design Philosophy

## Traditional Architecture (Bad)

```text
Core
 ├─ Ollama Logic
 ├─ Docker Logic
 ├─ Playwright Logic
 ├─ Flight Logic
 ├─ Weather Logic
 └─ Business Logic
```

Problems:

- Core becomes huge
- Difficult to maintain
- Impossible to scale dynamically
- Every new feature requires core modification
- Runtime cannot self-evolve

---

## Dynamic Capability Architecture (Correct)

```text
Core
 ├─ Workflow Engine
 ├─ Capability Resolver
 ├─ Execution Runtime
 ├─ Approval System
 ├─ Learning Engine
 └─ Memory System

Runtime
 ├─ Generated Capabilities
 ├─ Generated Prompts
 ├─ Generated Workflows
 ├─ Generated Tools
 ├─ Generated Registries
 └─ Generated Knowledge
```

Core never changes.

Runtime continuously evolves.

---

# High-Level Architecture

```text
User Input
    ↓
Input Parsing
    ↓
Intent Recognition
    ↓
Context Awareness
    ↓
Workflow Planning
    ↓
Capability Resolution
    ↓
Tool / Agent Execution
    ↓
Feedback Learning
    ↓
Output
```

---

# Key Features

## Dynamic Capability System

The runtime can dynamically:

- Generate new capabilities
- Install missing environments
- Detect missing dependencies
- Register providers
- Start services
- Verify environments
- Resume workflows

---

# Self-Healing Runtime

The runtime automatically handles:

```text
Missing binary
Missing environment
Missing model
Missing package
Missing service
Broken CLI
Timeout
Interactive prompts
```

---

# CLI Automation Engine

Supports:

```text
PTY
Auto Answer
Retry
Recovery
Timeout
Streaming Console
Progress Tracking
```

---

# Human-in-the-Loop AI

All critical actions support approval.

---

# Runtime Evolution

```text
Success Cases
↓
Knowledge Base
↓
Fine-tune Dataset
↓
Prompt Optimization
↓
Workflow Optimization
↓
Capability Expansion
```

---

# Repository Structure

```text
project/
│
├─ ai_core/
├─ runtime/
├─ configs/
├─ schema/
├─ tools/
├─ apps/
└─ scripts/
```

---

# Startup

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
python main.py
```

## Open UI

```text
http://127.0.0.1:8000
```

---

# Final Philosophy

This project is:

```text
A Dynamic AI Runtime Operating System
```

Where:

```text
Core remains stable
Runtime continuously evolves
Capabilities continuously expand
Knowledge continuously accumulates
Humans remain part of the decision loop
```

# AI Core Dynamic Capability Runtime v2

This version fixes the previous skeleton behavior.

## Changes in v2

1. UI
   - User input is shown on the right side.
   - System/runtime messages are shown on the left side.
   - Smaller console-like font.
   - Human review supports Approve / Reject / Modify.

2. Core
   - Capability readiness is not treated as the node result.
   - After a capability is ready, the node is actually executed by a generic node runner.

3. Human Review
   - Approve: continue the workflow.
   - Reject: enter a reason and retry the current node.
   - Modify: edit the JSON result and continue with the modified value.

4. Input Parsing
   - The input parsing node performs real structural parsing.
   - It outputs:
     - language
     - intent_type
     - tasks
     - missing_information
     - required_capabilities
     - safety_notes
     - original_input

## Run

```bash
pip install -r requirements.txt
python main.py
```

Open:

```text
http://127.0.0.1:8000
```

# AI Core Config-Driven Node Runtime v3

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

# AI Core Config-Driven Node Runtime v6

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


## v6 Fix

- Updated UI version label from v3 to v6.
- Added `/api/version`.
- Added no-cache headers for `/`.
- This avoids confusion when the browser or an old server process displays stale UI text.


## v6 Fix

- Fixed JavaScript syntax errors in `apps/web/index.html`.
- `/api/chat` now returns `run_id` immediately.
- Workflow execution starts in a background task.
- UI now displays `POST /api/chat` errors and SSE connection status.
- Added `.vscode/launch.json` and `.vscode/tasks.json`.


# AI Core Config-Driven Node Runtime v7

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


## v7 Fix

- Updated UI version label from v3 to v7.
- Added `/api/version`.
- Added no-cache headers for `/`.
- This avoids confusion when the browser or an old server process displays stale UI text.


## v7 Fix

- Fixed JavaScript syntax errors in `apps/web/index.html`.
- `/api/chat` now returns `run_id` immediately.
- Workflow execution starts in a background task.
- UI now displays `POST /api/chat` errors and SSE connection status.
- Added `.vscode/launch.json` and `.vscode/tasks.json`.


## v7 Update

- Added `runtime/generated/adapters/*.yaml`.
- `LLMJsonExecutor` calls a real configured provider instead of returning a placeholder.
- Provider config is generated at `runtime/configs/models/providers.yaml`.
- Supported provider protocols:
  - Ollama `/api/chat`
  - OpenAI Chat Completions
- If no provider is available, the workflow shows a clear `Node execution failed` message.
- `ai_core` still has no domain/task/business logic.


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


# AI Core Config-Driven Node Runtime v10

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


## v10 Fix

- Updated UI version label from v3 to v10.
- Added `/api/version`.
- Added no-cache headers for `/`.
- This avoids confusion when the browser or an old server process displays stale UI text.


## v10 Fix

- Fixed JavaScript syntax errors in `apps/web/index.html`.
- `/api/chat` now returns `run_id` immediately.
- Workflow execution starts in a background task.
- UI now displays `POST /api/chat` errors and SSE connection status.
- Added `.vscode/launch.json` and `.vscode/tasks.json`.


## v10 Update

- Added `runtime/generated/adapters/*.yaml`.
- `LLMJsonExecutor` calls a real configured provider instead of returning a placeholder.
- Provider config is generated at `runtime/configs/models/providers.yaml`.
- Supported provider protocols:
  - Ollama `/api/chat`
  - OpenAI Chat Completions
- If no provider is available, the workflow shows a clear `Node execution failed` message.
- `ai_core` still has no domain/task/business logic.


## v10 Update

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


## v10 Update

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


## v10 Fix

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


# AI Core Config-Driven Node Runtime v11

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


## v11 Fix

- Updated UI version label from v3 to v11.
- Added `/api/version`.
- Added no-cache headers for `/`.
- This avoids confusion when the browser or an old server process displays stale UI text.


## v11 Fix

- Fixed JavaScript syntax errors in `apps/web/index.html`.
- `/api/chat` now returns `run_id` immediately.
- Workflow execution starts in a background task.
- UI now displays `POST /api/chat` errors and SSE connection status.
- Added `.vscode/launch.json` and `.vscode/tasks.json`.


## v11 Update

- Added `runtime/generated/adapters/*.yaml`.
- `LLMJsonExecutor` calls a real configured provider instead of returning a placeholder.
- Provider config is generated at `runtime/configs/models/providers.yaml`.
- Supported provider protocols:
  - Ollama `/api/chat`
  - OpenAI Chat Completions
- If no provider is available, the workflow shows a clear `Node execution failed` message.
- `ai_core` still has no domain/task/business logic.


## v11 Update

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


## v11 Update

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


## v11 Fix

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


## v11 Update

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


# AI Core Config-Driven Node Runtime v12

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


## v12 Fix

- Updated UI version label from v3 to v12.
- Added `/api/version`.
- Added no-cache headers for `/`.
- This avoids confusion when the browser or an old server process displays stale UI text.


## v12 Fix

- Fixed JavaScript syntax errors in `apps/web/index.html`.
- `/api/chat` now returns `run_id` immediately.
- Workflow execution starts in a background task.
- UI now displays `POST /api/chat` errors and SSE connection status.
- Added `.vscode/launch.json` and `.vscode/tasks.json`.


## v12 Update

- Added `runtime/generated/adapters/*.yaml`.
- `LLMJsonExecutor` calls a real configured provider instead of returning a placeholder.
- Provider config is generated at `runtime/configs/models/providers.yaml`.
- Supported provider protocols:
  - Ollama `/api/chat`
  - OpenAI Chat Completions
- If no provider is available, the workflow shows a clear `Node execution failed` message.
- `ai_core` still has no domain/task/business logic.


## v12 Update

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


## v12 Update

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


## v12 Fix

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


## v12 Update

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


## v12 Update

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
Any /v1/chat/completions compatible service
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

# AI Core Config-Driven Node Runtime v13

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


## v13 Fix

- Updated UI version label from v3 to v13.
- Added `/api/version`.
- Added no-cache headers for `/`.
- This avoids confusion when the browser or an old server process displays stale UI text.


## v13 Fix

- Fixed JavaScript syntax errors in `apps/web/index.html`.
- `/api/chat` now returns `run_id` immediately.
- Workflow execution starts in a background task.
- UI now displays `POST /api/chat` errors and SSE connection status.
- Added `.vscode/launch.json` and `.vscode/tasks.json`.


## v13 Update

- Added `runtime/generated/adapters/*.yaml`.
- `LLMJsonExecutor` calls a real configured provider instead of returning a placeholder.
- Provider config is generated at `runtime/configs/models/providers.yaml`.
- Supported provider protocols:
  - Ollama `/api/chat`
  - OpenAI Chat Completions
- If no provider is available, the workflow shows a clear `Node execution failed` message.
- `ai_core` still has no domain/task/business logic.


## v13 Update

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


## v13 Update

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


## v13 Fix

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


## v13 Update

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


## v13 Update

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
Any /v1/chat/completions compatible service
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


## v13 Update

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

# AI Core Config-Driven Node Runtime v14

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


## v14 Fix

- Updated UI version label from v3 to v14.
- Added `/api/version`.
- Added no-cache headers for `/`.
- This avoids confusion when the browser or an old server process displays stale UI text.


## v14 Fix

- Fixed JavaScript syntax errors in `apps/web/index.html`.
- `/api/chat` now returns `run_id` immediately.
- Workflow execution starts in a background task.
- UI now displays `POST /api/chat` errors and SSE connection status.
- Added `.vscode/launch.json` and `.vscode/tasks.json`.


## v14 Update

- Added `runtime/generated/adapters/*.yaml`.
- `LLMJsonExecutor` calls a real configured provider instead of returning a placeholder.
- Provider config is generated at `runtime/configs/models/providers.yaml`.
- Supported provider protocols:
  - Ollama `/api/chat`
  - OpenAI Chat Completions
- If no provider is available, the workflow shows a clear `Node execution failed` message.
- `ai_core` still has no domain/task/business logic.


## v14 Update

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


## v14 Update

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


## v14 Fix

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


## v14 Update

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


## v14 Update

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
Any /v1/chat/completions compatible service
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


## v14 Update

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


## v14 Update

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

# AI Core Config-Driven Node Runtime v16

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


## v16 Fix

- Updated UI version label from v3 to v16.
- Added `/api/version`.
- Added no-cache headers for `/`.
- This avoids confusion when the browser or an old server process displays stale UI text.


## v16 Fix

- Fixed JavaScript syntax errors in `apps/web/index.html`.
- `/api/chat` now returns `run_id` immediately.
- Workflow execution starts in a background task.
- UI now displays `POST /api/chat` errors and SSE connection status.
- Added `.vscode/launch.json` and `.vscode/tasks.json`.


## v16 Update

- Added `runtime/generated/adapters/*.yaml`.
- `LLMJsonExecutor` calls a real configured provider instead of returning a placeholder.
- Provider config is generated at `runtime/configs/models/providers.yaml`.
- Supported provider protocols:
  - Ollama `/api/chat`
  - OpenAI Chat Completions
- If no provider is available, the workflow shows a clear `Node execution failed` message.
- `ai_core` still has no domain/task/business logic.


## v16 Update

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


## v16 Update

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


## v16 Fix

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


## v16 Update

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


## v16 Update

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
Any /v1/chat/completions compatible service
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


## v16 Update

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


## v16 Update

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


## v16 Update

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


## v16 Update

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

# AI Core Config-Driven Node Runtime v19

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


## v19 Fix

- Updated UI version label from v19 to v19.
- Added `/api/version`.
- Added no-cache headers for `/`.
- This avoids confusion when the browser or an old server process displays stale UI text.


## v19 Fix

- Fixed JavaScript syntax errors in `apps/web/index.html`.
- `/api/chat` now returns `run_id` immediately.
- Workflow execution starts in a background task.
- UI now displays `POST /api/chat` errors and SSE connection status.
- Added `.vscode/launch.json` and `.vscode/tasks.json`.


## v19 Update

- Added `runtime/generated/adapters/*.yaml`.
- `LLMJsonExecutor` calls a real configured provider instead of returning a placeholder.
- Provider config is generated at `runtime/configs/models/providers.yaml`.
- Supported provider protocols:
  - Ollama `/api/chat`
  - OpenAI Chat Completions
- If no provider is available, the workflow shows a clear `Node execution failed` message.
- `ai_core` still has no domain/task/business logic.


## v19 Update

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


## v19 Update

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


## v19 Fix

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


## v19 Update

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


## v19 Update

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
Any /v19/chat/completions compatible service
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


## v19 Update

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


## v19 Update

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


## v19 Update

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


## v19 Update

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


## v19 Update

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


## v19 Update

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


## v19 Update

### Hierarchical interaction UI

- Running nodes now show a spinner in the node status pill.
- User input is now displayed inside the `runtime` workflow hierarchy.
- Human Review is displayed inside the related node card instead of as a separate flat card.
- API Key input is displayed inside the workflow hierarchy.
- Long-running tasks still lock the main input.

### Clearer Ollama timeout error

When Ollama inference exceeds `timeout_seconds`, the error now includes:

```text
endpoint
model
timeout_seconds
suggested mitigation
```

This makes it clear whether the issue is installation, model availability, or slow inference.
