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


# AI Core Config-Driven Node Runtime v21

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


## v21 Fix

- Updated UI version label from v21 to v21.
- Added `/api/version`.
- Added no-cache headers for `/`.
- This avoids confusion when the browser or an old server process displays stale UI text.


## v21 Fix

- Fixed JavaScript syntax errors in `apps/web/index.html`.
- `/api/chat` now returns `run_id` immediately.
- Workflow execution starts in a background task.
- UI now displays `POST /api/chat` errors and SSE connection status.
- Added `.vscode/launch.json` and `.vscode/tasks.json`.


## v21 Update

- Added `runtime/generated/adapters/*.yaml`.
- `LLMJsonExecutor` calls a real configured provider instead of returning a placeholder.
- Provider config is generated at `runtime/configs/models/providers.yaml`.
- Supported provider protocols:
  - Ollama `/api/chat`
  - OpenAI Chat Completions
- If no provider is available, the workflow shows a clear `Node execution failed` message.
- `ai_core` still has no domain/task/business logic.


## v21 Update

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


## v21 Update

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


## v21 Fix

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


## v21 Update

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


## v21 Update

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
Any /v21/chat/completions compatible service
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


## v21 Update

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


## v21 Update

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


## v21 Update

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


## v21 Update

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


## v21 Update

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


## v21 Update

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


## v21 Update

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


## v21 Update

### Paused Human Interaction UI

Human interaction now behaves visually as a blocking checkpoint:

```text
node attempt 1
↓
Human Review: waiting
↓
user clicks Approve / Reject / Modify
↓
interaction is marked resolved
↓
workflow continues
```

### Retry Attempt Grouping

When `Reject & Retry` reruns the same node, the UI creates a new attempt card:

```text
intent_recognition / attempt 1
  └─ Human Review: resolved

intent_recognition / attempt 2
  └─ capability
  └─ provider
  └─ validation
```

This prevents new events from visually pushing the active human interaction upward inside the same node card.


## v21 Update

### Auto Schema Repair

When LLM JSON is structurally useful but the generated schema is too old or too narrow, runtime tries to repair the schema automatically before stopping for human recovery.

Example:

```text
confidence object is not of type number
```

Runtime can automatically evolve:

```json
"confidence": {"type": "number"}
```

into:

```json
"confidence": {
  "anyOf": [
    {"type": "number"},
    {"type": "object"}
  ]
}
```

Then it re-validates the same model output and continues the workflow if validation passes.

### Recovery order

```text
LLM JSON
↓
Schema validation
↓
If failed:
  auto schema repair
  ↓
  re-validation
  ↓
  continue if valid
↓
If still failed:
  Human recovery
```

Auto repair events are recorded in:

```text
runtime/knowledge/schema_auto_repair.jsonl
```


# AI Core Config-Driven Node Runtime v23

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


## v23 Fix

- Updated UI version label from v23 to v23.
- Added `/api/version`.
- Added no-cache headers for `/`.
- This avoids confusion when the browser or an old server process displays stale UI text.


## v23 Fix

- Fixed JavaScript syntax errors in `apps/web/index.html`.
- `/api/chat` now returns `run_id` immediately.
- Workflow execution starts in a background task.
- UI now displays `POST /api/chat` errors and SSE connection status.
- Added `.vscode/launch.json` and `.vscode/tasks.json`.


## v23 Update

- Added `runtime/generated/adapters/*.yaml`.
- `LLMJsonExecutor` calls a real configured provider instead of returning a placeholder.
- Provider config is generated at `runtime/configs/models/providers.yaml`.
- Supported provider protocols:
  - Ollama `/api/chat`
  - OpenAI Chat Completions
- If no provider is available, the workflow shows a clear `Node execution failed` message.
- `ai_core` still has no domain/task/business logic.


## v23 Update

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


## v23 Update

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


## v23 Fix

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


## v23 Update

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


## v23 Update

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
Any /v23/chat/completions compatible service
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


## v23 Update

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


## v23 Update

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


## v23 Update

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


## v23 Update

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


## v23 Update

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


## v23 Update

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


## v23 Update

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


## v23 Update

### Paused Human Interaction UI

Human interaction now behaves visually as a blocking checkpoint:

```text
node attempt 1
↓
Human Review: waiting
↓
user clicks Approve / Reject / Modify
↓
interaction is marked resolved
↓
workflow continues
```

### Retry Attempt Grouping

When `Reject & Retry` reruns the same node, the UI creates a new attempt card:

```text
intent_recognition / attempt 1
  └─ Human Review: resolved

intent_recognition / attempt 2
  └─ capability
  └─ provider
  └─ validation
```

This prevents new events from visually pushing the active human interaction upward inside the same node card.


## v23 Update

### Auto Schema Repair

When LLM JSON is structurally useful but the generated schema is too old or too narrow, runtime tries to repair the schema automatically before stopping for human recovery.

Example:

```text
confidence object is not of type number
```

Runtime can automatically evolve:

```json
"confidence": {"type": "number"}
```

into:

```json
"confidence": {
  "anyOf": [
    {"type": "number"},
    {"type": "object"}
  ]
}
```

Then it re-validates the same model output and continues the workflow if validation passes.

### Recovery order

```text
LLM JSON
↓
Schema validation
↓
If failed:
  auto schema repair
  ↓
  re-validation
  ↓
  continue if valid
↓
If still failed:
  Human recovery
```

Auto repair events are recorded in:

```text
runtime/knowledge/schema_auto_repair.jsonl
```


## v23 Update

### Sticky Blocking Interaction Panel

Human Review and API Key input are now displayed in a fixed bottom panel above the normal composer.

When a blocking interaction appears:

```text
workflowPaused = true
activeInteraction = event
normal input remains disabled
sticky interaction panel appears above composer
timeline receives a placeholder only
subsequent non-terminal events are buffered
```

When the user clicks:

```text
Approve
Reject & Retry
Modify JSON & Continue
Save Key & Continue
```

the UI:

```text
marks the interaction as resolved
hides the sticky panel
flushes buffered events
continues normal rendering
```

This prevents Human Review input from being pushed upward by later workflow logs.


## v23 Update

### Result Auto Repair

This version fixes cases where the model output is close to correct but omits required fields.

Example:

```text
JSON validation failed:
'intent_type' is a required property
```

Runtime now tries:

```text
schema validation failed
↓
result auto repair
  - find missing field from previous_results
  - find missing field from human feedback
  - otherwise use schema-safe default
↓
validate repaired result
↓
continue workflow if valid
↓
if still invalid, try schema auto repair
↓
if still invalid, Human Recovery
```

For example, if `intent_recognition` output omits `intent_type`, runtime can copy it from prior `input_parsing` result.

Repair log:

```text
runtime/knowledge/result_auto_repair.jsonl
```


# AI Core Config-Driven Node Runtime v24

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


## v24 Fix

- Updated UI version label from v24 to v24.
- Added `/api/version`.
- Added no-cache headers for `/`.
- This avoids confusion when the browser or an old server process displays stale UI text.


## v24 Fix

- Fixed JavaScript syntax errors in `apps/web/index.html`.
- `/api/chat` now returns `run_id` immediately.
- Workflow execution starts in a background task.
- UI now displays `POST /api/chat` errors and SSE connection status.
- Added `.vscode/launch.json` and `.vscode/tasks.json`.


## v24 Update

- Added `runtime/generated/adapters/*.yaml`.
- `LLMJsonExecutor` calls a real configured provider instead of returning a placeholder.
- Provider config is generated at `runtime/configs/models/providers.yaml`.
- Supported provider protocols:
  - Ollama `/api/chat`
  - OpenAI Chat Completions
- If no provider is available, the workflow shows a clear `Node execution failed` message.
- `ai_core` still has no domain/task/business logic.


## v24 Update

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


## v24 Update

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


## v24 Fix

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


## v24 Update

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


## v24 Update

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
Any /v24/chat/completions compatible service
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


## v24 Update

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


## v24 Update

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


## v24 Update

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


## v24 Update

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


## v24 Update

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


## v24 Update

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


## v24 Update

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


## v24 Update

### Paused Human Interaction UI

Human interaction now behaves visually as a blocking checkpoint:

```text
node attempt 1
↓
Human Review: waiting
↓
user clicks Approve / Reject / Modify
↓
interaction is marked resolved
↓
workflow continues
```

### Retry Attempt Grouping

When `Reject & Retry` reruns the same node, the UI creates a new attempt card:

```text
intent_recognition / attempt 1
  └─ Human Review: resolved

intent_recognition / attempt 2
  └─ capability
  └─ provider
  └─ validation
```

This prevents new events from visually pushing the active human interaction upward inside the same node card.


## v24 Update

### Auto Schema Repair

When LLM JSON is structurally useful but the generated schema is too old or too narrow, runtime tries to repair the schema automatically before stopping for human recovery.

Example:

```text
confidence object is not of type number
```

Runtime can automatically evolve:

```json
"confidence": {"type": "number"}
```

into:

```json
"confidence": {
  "anyOf": [
    {"type": "number"},
    {"type": "object"}
  ]
}
```

Then it re-validates the same model output and continues the workflow if validation passes.

### Recovery order

```text
LLM JSON
↓
Schema validation
↓
If failed:
  auto schema repair
  ↓
  re-validation
  ↓
  continue if valid
↓
If still failed:
  Human recovery
```

Auto repair events are recorded in:

```text
runtime/knowledge/schema_auto_repair.jsonl
```


## v24 Update

### Sticky Blocking Interaction Panel

Human Review and API Key input are now displayed in a fixed bottom panel above the normal composer.

When a blocking interaction appears:

```text
workflowPaused = true
activeInteraction = event
normal input remains disabled
sticky interaction panel appears above composer
timeline receives a placeholder only
subsequent non-terminal events are buffered
```

When the user clicks:

```text
Approve
Reject & Retry
Modify JSON & Continue
Save Key & Continue
```

the UI:

```text
marks the interaction as resolved
hides the sticky panel
flushes buffered events
continues normal rendering
```

This prevents Human Review input from being pushed upward by later workflow logs.


## v24 Update

### Result Auto Repair

This version fixes cases where the model output is close to correct but omits required fields.

Example:

```text
JSON validation failed:
'intent_type' is a required property
```

Runtime now tries:

```text
schema validation failed
↓
result auto repair
  - find missing field from previous_results
  - find missing field from human feedback
  - otherwise use schema-safe default
↓
validate repaired result
↓
continue workflow if valid
↓
if still invalid, try schema auto repair
↓
if still invalid, Human Recovery
```

For example, if `intent_recognition` output omits `intent_type`, runtime can copy it from prior `input_parsing` result.

Repair log:

```text
runtime/knowledge/result_auto_repair.jsonl
```


## v24 Update

### Fixed Result Auto Repair Continuation

`RESULT_AUTO_REPAIRED` no longer leaves the node visually stuck.

Executor validation flow is now:

```text
validate original result
↓
if invalid, try result repair
↓
if repaired result validates:
  continue immediately
↓
else try schema repair
↓
if repaired schema validates:
  continue
↓
else human recovery
```

### Collapsed Human Interaction History

Resolved human interactions are now stored as collapsed details inside the node card instead of occupying a large visible area.

### UI Running State Fix

After a human interaction is resolved, the main composer stays disabled and shows `Thinking...` until the workflow actually completes/fails/cancels.


# AI Core Config-Driven Node Runtime v25

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


## v25 Fix

- Updated UI version label from v25 to v25.
- Added `/api/version`.
- Added no-cache headers for `/`.
- This avoids confusion when the browser or an old server process displays stale UI text.


## v25 Fix

- Fixed JavaScript syntax errors in `apps/web/index.html`.
- `/api/chat` now returns `run_id` immediately.
- Workflow execution starts in a background task.
- UI now displays `POST /api/chat` errors and SSE connection status.
- Added `.vscode/launch.json` and `.vscode/tasks.json`.


## v25 Update

- Added `runtime/generated/adapters/*.yaml`.
- `LLMJsonExecutor` calls a real configured provider instead of returning a placeholder.
- Provider config is generated at `runtime/configs/models/providers.yaml`.
- Supported provider protocols:
  - Ollama `/api/chat`
  - OpenAI Chat Completions
- If no provider is available, the workflow shows a clear `Node execution failed` message.
- `ai_core` still has no domain/task/business logic.


## v25 Update

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


## v25 Update

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


## v25 Fix

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


## v25 Update

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


## v25 Update

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
Any /v25/chat/completions compatible service
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


## v25 Update

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


## v25 Update

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


## v25 Update

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


## v25 Update

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


## v25 Update

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


## v25 Update

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


## v25 Update

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


## v25 Update

### Paused Human Interaction UI

Human interaction now behaves visually as a blocking checkpoint:

```text
node attempt 1
↓
Human Review: waiting
↓
user clicks Approve / Reject / Modify
↓
interaction is marked resolved
↓
workflow continues
```

### Retry Attempt Grouping

When `Reject & Retry` reruns the same node, the UI creates a new attempt card:

```text
intent_recognition / attempt 1
  └─ Human Review: resolved

intent_recognition / attempt 2
  └─ capability
  └─ provider
  └─ validation
```

This prevents new events from visually pushing the active human interaction upward inside the same node card.


## v25 Update

### Auto Schema Repair

When LLM JSON is structurally useful but the generated schema is too old or too narrow, runtime tries to repair the schema automatically before stopping for human recovery.

Example:

```text
confidence object is not of type number
```

Runtime can automatically evolve:

```json
"confidence": {"type": "number"}
```

into:

```json
"confidence": {
  "anyOf": [
    {"type": "number"},
    {"type": "object"}
  ]
}
```

Then it re-validates the same model output and continues the workflow if validation passes.

### Recovery order

```text
LLM JSON
↓
Schema validation
↓
If failed:
  auto schema repair
  ↓
  re-validation
  ↓
  continue if valid
↓
If still failed:
  Human recovery
```

Auto repair events are recorded in:

```text
runtime/knowledge/schema_auto_repair.jsonl
```


## v25 Update

### Sticky Blocking Interaction Panel

Human Review and API Key input are now displayed in a fixed bottom panel above the normal composer.

When a blocking interaction appears:

```text
workflowPaused = true
activeInteraction = event
normal input remains disabled
sticky interaction panel appears above composer
timeline receives a placeholder only
subsequent non-terminal events are buffered
```

When the user clicks:

```text
Approve
Reject & Retry
Modify JSON & Continue
Save Key & Continue
```

the UI:

```text
marks the interaction as resolved
hides the sticky panel
flushes buffered events
continues normal rendering
```

This prevents Human Review input from being pushed upward by later workflow logs.


## v25 Update

### Result Auto Repair

This version fixes cases where the model output is close to correct but omits required fields.

Example:

```text
JSON validation failed:
'intent_type' is a required property
```

Runtime now tries:

```text
schema validation failed
↓
result auto repair
  - find missing field from previous_results
  - find missing field from human feedback
  - otherwise use schema-safe default
↓
validate repaired result
↓
continue workflow if valid
↓
if still invalid, try schema auto repair
↓
if still invalid, Human Recovery
```

For example, if `intent_recognition` output omits `intent_type`, runtime can copy it from prior `input_parsing` result.

Repair log:

```text
runtime/knowledge/result_auto_repair.jsonl
```


## v25 Update

### Fixed Result Auto Repair Continuation

`RESULT_AUTO_REPAIRED` no longer leaves the node visually stuck.

Executor validation flow is now:

```text
validate original result
↓
if invalid, try result repair
↓
if repaired result validates:
  continue immediately
↓
else try schema repair
↓
if repaired schema validates:
  continue
↓
else human recovery
```

### Collapsed Human Interaction History

Resolved human interactions are now stored as collapsed details inside the node card instead of occupying a large visible area.

### UI Running State Fix

After a human interaction is resolved, the main composer stays disabled and shows `Thinking...` until the workflow actually completes/fails/cancels.


## v25 Update

### Fixed Schema Auto Repair Path Bug

Fixed:

```text
'str' object has no attribute 'parent'
```

Cause:

```text
SchemaAutoRepair.try_repair() received schema_path as str
but ConfigLoader.save_json() expects a Path-like object and uses .parent
```

Fix:

```python
self.loader.save_json(Path(schema_path), repaired)
```

Also adjusted the LLM JSON executor to pass `schema_path` as a Path object when calling schema auto repair.

This allows the workflow to continue after:

```text
RESULT_AUTO_REPAIRED
↓
SCHEMA_AUTO_REPAIRED
↓
re-validation
↓
continue workflow
```

# AI Core Config-Driven Node Runtime v29

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


## v29 Fix

- Updated UI version label from v29 to v29.
- Added `/api/version`.
- Added no-cache headers for `/`.
- This avoids confusion when the browser or an old server process displays stale UI text.


## v29 Fix

- Fixed JavaScript syntax errors in `apps/web/index.html`.
- `/api/chat` now returns `run_id` immediately.
- Workflow execution starts in a background task.
- UI now displays `POST /api/chat` errors and SSE connection status.
- Added `.vscode/launch.json` and `.vscode/tasks.json`.


## v29 Update

- Added `runtime/generated/adapters/*.yaml`.
- `LLMJsonExecutor` calls a real configured provider instead of returning a placeholder.
- Provider config is generated at `runtime/configs/models/providers.yaml`.
- Supported provider protocols:
  - Ollama `/api/chat`
  - OpenAI Chat Completions
- If no provider is available, the workflow shows a clear `Node execution failed` message.
- `ai_core` still has no domain/task/business logic.


## v29 Update

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


## v29 Update

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


## v29 Fix

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


## v29 Update

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


## v29 Update

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
Any /v29/chat/completions compatible service
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


## v29 Update

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


## v29 Update

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


## v29 Update

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


## v29 Update

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


## v29 Update

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


## v29 Update

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


## v29 Update

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


## v29 Update

### Paused Human Interaction UI

Human interaction now behaves visually as a blocking checkpoint:

```text
node attempt 1
↓
Human Review: waiting
↓
user clicks Approve / Reject / Modify
↓
interaction is marked resolved
↓
workflow continues
```

### Retry Attempt Grouping

When `Reject & Retry` reruns the same node, the UI creates a new attempt card:

```text
intent_recognition / attempt 1
  └─ Human Review: resolved

intent_recognition / attempt 2
  └─ capability
  └─ provider
  └─ validation
```

This prevents new events from visually pushing the active human interaction upward inside the same node card.


## v29 Update

### Auto Schema Repair

When LLM JSON is structurally useful but the generated schema is too old or too narrow, runtime tries to repair the schema automatically before stopping for human recovery.

Example:

```text
confidence object is not of type number
```

Runtime can automatically evolve:

```json
"confidence": {"type": "number"}
```

into:

```json
"confidence": {
  "anyOf": [
    {"type": "number"},
    {"type": "object"}
  ]
}
```

Then it re-validates the same model output and continues the workflow if validation passes.

### Recovery order

```text
LLM JSON
↓
Schema validation
↓
If failed:
  auto schema repair
  ↓
  re-validation
  ↓
  continue if valid
↓
If still failed:
  Human recovery
```

Auto repair events are recorded in:

```text
runtime/knowledge/schema_auto_repair.jsonl
```


## v29 Update

### Sticky Blocking Interaction Panel

Human Review and API Key input are now displayed in a fixed bottom panel above the normal composer.

When a blocking interaction appears:

```text
workflowPaused = true
activeInteraction = event
normal input remains disabled
sticky interaction panel appears above composer
timeline receives a placeholder only
subsequent non-terminal events are buffered
```

When the user clicks:

```text
Approve
Reject & Retry
Modify JSON & Continue
Save Key & Continue
```

the UI:

```text
marks the interaction as resolved
hides the sticky panel
flushes buffered events
continues normal rendering
```

This prevents Human Review input from being pushed upward by later workflow logs.


## v29 Update

### Result Auto Repair

This version fixes cases where the model output is close to correct but omits required fields.

Example:

```text
JSON validation failed:
'intent_type' is a required property
```

Runtime now tries:

```text
schema validation failed
↓
result auto repair
  - find missing field from previous_results
  - find missing field from human feedback
  - otherwise use schema-safe default
↓
validate repaired result
↓
continue workflow if valid
↓
if still invalid, try schema auto repair
↓
if still invalid, Human Recovery
```

For example, if `intent_recognition` output omits `intent_type`, runtime can copy it from prior `input_parsing` result.

Repair log:

```text
runtime/knowledge/result_auto_repair.jsonl
```


## v29 Update

### Fixed Result Auto Repair Continuation

`RESULT_AUTO_REPAIRED` no longer leaves the node visually stuck.

Executor validation flow is now:

```text
validate original result
↓
if invalid, try result repair
↓
if repaired result validates:
  continue immediately
↓
else try schema repair
↓
if repaired schema validates:
  continue
↓
else human recovery
```

### Collapsed Human Interaction History

Resolved human interactions are now stored as collapsed details inside the node card instead of occupying a large visible area.

### UI Running State Fix

After a human interaction is resolved, the main composer stays disabled and shows `Thinking...` until the workflow actually completes/fails/cancels.


## v29 Update

### Fixed Schema Auto Repair Path Bug

Fixed:

```text
'str' object has no attribute 'parent'
```

Cause:

```text
SchemaAutoRepair.try_repair() received schema_path as str
but ConfigLoader.save_json() expects a Path-like object and uses .parent
```

Fix:

```python
self.loader.save_json(Path(schema_path), repaired)
```

Also adjusted the LLM JSON executor to pass `schema_path` as a Path object when calling schema auto repair.

This allows the workflow to continue after:

```text
RESULT_AUTO_REPAIRED
↓
SCHEMA_AUTO_REPAIRED
↓
re-validation
↓
continue workflow
```


## v29 Update

### Generic Runtime Execution Planner

The `execution` node no longer returns only:

```json
{
  "_status": "tool_call_ready"
}
```

It now reads:

```text
previous_results.workflow_planning.planned_steps
```

and generates a generic execution state:

```text
execution_steps
blocked_steps
human_interactions
missing_tools
safety_holds
summary
```

### No business logic in ai_core

The executor does not know weather, flight, booking, payment, etc.

It only interprets generic fields:

```text
step_id
step_type
required_capability
execution_ready
human_interaction
requires_human_confirmation
parameters.missing_required
```

### Missing Tool Spec Generation

If a required capability has no registered tool, runtime creates a missing implementation spec under:

```text
runtime/generated/tools/generated_<capability>.json
```

and registers it in:

```text
runtime/registry/tool_registry.json
```

### Execution behavior

```text
workflow_planning.planned_steps
↓
execution planner
↓
ready steps / blocked steps / human interactions / missing tools
```

## v29 Update

### Runtime Approval Memory
Approve is now positive memory and is saved to:
- runtime/datasets/approved_outputs.jsonl
- runtime/knowledge/success_patterns.jsonl
- runtime/knowledge/prompt_optimization_memory.jsonl

### Runtime Tool Builder Blueprint
Missing capability now generates:
- runtime/generated/tools/<tool_id>/tool.json
- runtime/generated/tools/<tool_id>/tool.py
- runtime/generated/tools/<tool_id>/README.md
- runtime/generated/tools/<tool_id>/test_input.json
- runtime/generated/tool_generation_requests/<request_id>.json

### Browser Automation Blueprint
Browser automation capability generates:
- runtime/generated/browser_blueprints/<blueprint_id>/blueprint.json
- runtime/generated/browser_blueprints/<blueprint_id>/tool.py
- runtime/generated/browser_blueprints/<blueprint_id>/README.md

Safety policy:
- prepare page allowed
- discover elements allowed
- preview action allowed
- irreversible click/submit requires explicit human confirmation

### Strong Model Escalation Policy
Strong models are used as Runtime Architect / Tool Builder for complex workflow, new capability, browser automation, and tool code generation.


## v29 Update

### Core Semantic Cleanup

Removed domain/semantic parsing from ai_core.

Fixed examples:

```text
browser_automation_blueprint.py
- removed hardcoded time regex
- removed direct URL/time/schedule semantic extraction
- now only writes runtime-provided structured metadata

escalation_policy.py
- removed business/domain/language keywords
- now uses generic runtime signals and policy config only

tool_blueprint_builder.py
- removed strategy inference from capability or natural language words
- strategy must come from runtime metadata
```

### New Rule

ai_core must not parse business language such as time expressions, attendance words, booking words, browser action semantics, or website-specific concepts.

Correct flow:

```text
LLM/runtime planning
↓
generates structured metadata
↓
ai_core stores/dispatches/validates generic metadata
```

### Scanner

Added:

```text
tools/scan_core_semantics.py
```

Run:

```bash
python tools/scan_core_semantics.py
```

This helps detect suspicious semantic/domain words inside ai_core.


## v29 Update

### Runtime Module Builder

ai_core can now generate generic runtime module blueprints when a required capability has no module/tool implementation.

This keeps ai_core generic:

```text
ai_core does not implement scheduler/notification/web_query logic directly.
ai_core generates module blueprints and code generation requests from structured runtime metadata.
```

Generated module package:

```text
runtime/generated/modules/<module_id>/
  module.json
  module.py
  README.md
  test_input.json
```

Generated code request:

```text
runtime/generated/module_generation_requests/<request_id>.json
```

Registry:

```text
runtime/registry/module_registry.json
```

### Generic Module Interface

Generated modules are expected to expose:

```text
validate_config(config)
health_check()
run(input_data)
```

### Example Flow

```text
User asks for scheduling/reminder/automation
↓
LLM/runtime planning produces structured capability + module metadata
↓
execution detects missing capability
↓
RuntimeModuleBuilder generates module blueprint
↓
strong model codegen request is created
↓
human review / safety review
↓
module registered and reused later
```

### Core Rule

ai_core must not parse natural language time, appointment, reminder, business actions, or domain semantics.

Those must be produced as structured metadata by runtime planning/LLM, then ai_core can generate and run generic modules.


# AI Core Config-Driven Node Runtime v30

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


## v30 Fix

- Updated UI version label from v30 to v30.
- Added `/api/version`.
- Added no-cache headers for `/`.
- This avoids confusion when the browser or an old server process displays stale UI text.


## v30 Fix

- Fixed JavaScript syntax errors in `apps/web/index.html`.
- `/api/chat` now returns `run_id` immediately.
- Workflow execution starts in a background task.
- UI now displays `POST /api/chat` errors and SSE connection status.
- Added `.vscode/launch.json` and `.vscode/tasks.json`.


## v30 Update

- Added `runtime/generated/adapters/*.yaml`.
- `LLMJsonExecutor` calls a real configured provider instead of returning a placeholder.
- Provider config is generated at `runtime/configs/models/providers.yaml`.
- Supported provider protocols:
  - Ollama `/api/chat`
  - OpenAI Chat Completions
- If no provider is available, the workflow shows a clear `Node execution failed` message.
- `ai_core` still has no domain/task/business logic.


## v30 Update

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


## v30 Update

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


## v30 Fix

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


## v30 Update

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


## v30 Update

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
Any /v30/chat/completions compatible service
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


## v30 Update

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


## v30 Update

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


## v30 Update

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


## v30 Update

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


## v30 Update

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


## v30 Update

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


## v30 Update

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


## v30 Update

### Paused Human Interaction UI

Human interaction now behaves visually as a blocking checkpoint:

```text
node attempt 1
↓
Human Review: waiting
↓
user clicks Approve / Reject / Modify
↓
interaction is marked resolved
↓
workflow continues
```

### Retry Attempt Grouping

When `Reject & Retry` reruns the same node, the UI creates a new attempt card:

```text
intent_recognition / attempt 1
  └─ Human Review: resolved

intent_recognition / attempt 2
  └─ capability
  └─ provider
  └─ validation
```

This prevents new events from visually pushing the active human interaction upward inside the same node card.


## v30 Update

### Auto Schema Repair

When LLM JSON is structurally useful but the generated schema is too old or too narrow, runtime tries to repair the schema automatically before stopping for human recovery.

Example:

```text
confidence object is not of type number
```

Runtime can automatically evolve:

```json
"confidence": {"type": "number"}
```

into:

```json
"confidence": {
  "anyOf": [
    {"type": "number"},
    {"type": "object"}
  ]
}
```

Then it re-validates the same model output and continues the workflow if validation passes.

### Recovery order

```text
LLM JSON
↓
Schema validation
↓
If failed:
  auto schema repair
  ↓
  re-validation
  ↓
  continue if valid
↓
If still failed:
  Human recovery
```

Auto repair events are recorded in:

```text
runtime/knowledge/schema_auto_repair.jsonl
```


## v30 Update

### Sticky Blocking Interaction Panel

Human Review and API Key input are now displayed in a fixed bottom panel above the normal composer.

When a blocking interaction appears:

```text
workflowPaused = true
activeInteraction = event
normal input remains disabled
sticky interaction panel appears above composer
timeline receives a placeholder only
subsequent non-terminal events are buffered
```

When the user clicks:

```text
Approve
Reject & Retry
Modify JSON & Continue
Save Key & Continue
```

the UI:

```text
marks the interaction as resolved
hides the sticky panel
flushes buffered events
continues normal rendering
```

This prevents Human Review input from being pushed upward by later workflow logs.


## v30 Update

### Result Auto Repair

This version fixes cases where the model output is close to correct but omits required fields.

Example:

```text
JSON validation failed:
'intent_type' is a required property
```

Runtime now tries:

```text
schema validation failed
↓
result auto repair
  - find missing field from previous_results
  - find missing field from human feedback
  - otherwise use schema-safe default
↓
validate repaired result
↓
continue workflow if valid
↓
if still invalid, try schema auto repair
↓
if still invalid, Human Recovery
```

For example, if `intent_recognition` output omits `intent_type`, runtime can copy it from prior `input_parsing` result.

Repair log:

```text
runtime/knowledge/result_auto_repair.jsonl
```


## v30 Update

### Fixed Result Auto Repair Continuation

`RESULT_AUTO_REPAIRED` no longer leaves the node visually stuck.

Executor validation flow is now:

```text
validate original result
↓
if invalid, try result repair
↓
if repaired result validates:
  continue immediately
↓
else try schema repair
↓
if repaired schema validates:
  continue
↓
else human recovery
```

### Collapsed Human Interaction History

Resolved human interactions are now stored as collapsed details inside the node card instead of occupying a large visible area.

### UI Running State Fix

After a human interaction is resolved, the main composer stays disabled and shows `Thinking...` until the workflow actually completes/fails/cancels.


## v30 Update

### Fixed Schema Auto Repair Path Bug

Fixed:

```text
'str' object has no attribute 'parent'
```

Cause:

```text
SchemaAutoRepair.try_repair() received schema_path as str
but ConfigLoader.save_json() expects a Path-like object and uses .parent
```

Fix:

```python
self.loader.save_json(Path(schema_path), repaired)
```

Also adjusted the LLM JSON executor to pass `schema_path` as a Path object when calling schema auto repair.

This allows the workflow to continue after:

```text
RESULT_AUTO_REPAIRED
↓
SCHEMA_AUTO_REPAIRED
↓
re-validation
↓
continue workflow
```


## v30 Update

### Generic Runtime Execution Planner

The `execution` node no longer returns only:

```json
{
  "_status": "tool_call_ready"
}
```

It now reads:

```text
previous_results.workflow_planning.planned_steps
```

and generates a generic execution state:

```text
execution_steps
blocked_steps
human_interactions
missing_tools
safety_holds
summary
```

### No business logic in ai_core

The executor does not know weather, flight, booking, payment, etc.

It only interprets generic fields:

```text
step_id
step_type
required_capability
execution_ready
human_interaction
requires_human_confirmation
parameters.missing_required
```

### Missing Tool Spec Generation

If a required capability has no registered tool, runtime creates a missing implementation spec under:

```text
runtime/generated/tools/generated_<capability>.json
```

and registers it in:

```text
runtime/registry/tool_registry.json
```

### Execution behavior

```text
workflow_planning.planned_steps
↓
execution planner
↓
ready steps / blocked steps / human interactions / missing tools
```

## v30 Update

### Runtime Approval Memory
Approve is now positive memory and is saved to:
- runtime/datasets/approved_outputs.jsonl
- runtime/knowledge/success_patterns.jsonl
- runtime/knowledge/prompt_optimization_memory.jsonl

### Runtime Tool Builder Blueprint
Missing capability now generates:
- runtime/generated/tools/<tool_id>/tool.json
- runtime/generated/tools/<tool_id>/tool.py
- runtime/generated/tools/<tool_id>/README.md
- runtime/generated/tools/<tool_id>/test_input.json
- runtime/generated/tool_generation_requests/<request_id>.json

### Browser Automation Blueprint
Browser automation capability generates:
- runtime/generated/browser_blueprints/<blueprint_id>/blueprint.json
- runtime/generated/browser_blueprints/<blueprint_id>/tool.py
- runtime/generated/browser_blueprints/<blueprint_id>/README.md

Safety policy:
- prepare page allowed
- discover elements allowed
- preview action allowed
- irreversible click/submit requires explicit human confirmation

### Strong Model Escalation Policy
Strong models are used as Runtime Architect / Tool Builder for complex workflow, new capability, browser automation, and tool code generation.


## v30 Update

### Core Semantic Cleanup

Removed domain/semantic parsing from ai_core.

Fixed examples:

```text
browser_automation_blueprint.py
- removed hardcoded time regex
- removed direct URL/time/schedule semantic extraction
- now only writes runtime-provided structured metadata

escalation_policy.py
- removed business/domain/language keywords
- now uses generic runtime signals and policy config only

tool_blueprint_builder.py
- removed strategy inference from capability or natural language words
- strategy must come from runtime metadata
```

### New Rule

ai_core must not parse business language such as time expressions, attendance words, booking words, browser action semantics, or website-specific concepts.

Correct flow:

```text
LLM/runtime planning
↓
generates structured metadata
↓
ai_core stores/dispatches/validates generic metadata
```

### Scanner

Added:

```text
tools/scan_core_semantics.py
```

Run:

```bash
python tools/scan_core_semantics.py
```

This helps detect suspicious semantic/domain words inside ai_core.


## v30 Update

### Runtime Module Builder

ai_core can now generate generic runtime module blueprints when a required capability has no module/tool implementation.

This keeps ai_core generic:

```text
ai_core does not implement scheduler/notification/web_query logic directly.
ai_core generates module blueprints and code generation requests from structured runtime metadata.
```

Generated module package:

```text
runtime/generated/modules/<module_id>/
  module.json
  module.py
  README.md
  test_input.json
```

Generated code request:

```text
runtime/generated/module_generation_requests/<request_id>.json
```

Registry:

```text
runtime/registry/module_registry.json
```

### Generic Module Interface

Generated modules are expected to expose:

```text
validate_config(config)
health_check()
run(input_data)
```

### Example Flow

```text
User asks for scheduling/reminder/automation
↓
LLM/runtime planning produces structured capability + module metadata
↓
execution detects missing capability
↓
RuntimeModuleBuilder generates module blueprint
↓
strong model codegen request is created
↓
human review / safety review
↓
module registered and reused later
```

### Core Rule

ai_core must not parse natural language time, appointment, reminder, business actions, or domain semantics.

Those must be produced as structured metadata by runtime planning/LLM, then ai_core can generate and run generic modules.


## v30 Update

### Config-Driven Semantic Boundary Scanner

Removed hardcoded suspicious business/domain words from `tools/scan_core_semantics.py`.

New structure:

```text
ai_core/validation/semantic_boundary_scanner.py
  generic scanner engine only

tools/scan_core_semantics.py
  loads runtime policy

runtime/configs/policies/semantic_boundary.yaml
  project/runtime-generated rules
```

### Core Rule

`ai_core` must not contain business/domain forbidden words.

The scanner engine contains no domain knowledge. It only applies rules supplied by runtime config.

### Usage

```bash
python tools/scan_core_semantics.py
```

By default the policy is disabled:

```yaml
enabled: false
rules: []
```

### Policy Generation Request

Template added:

```text
runtime/generated/policies/semantic_boundary_policy_generation_request.json
```

This lets a stronger model generate a project-specific semantic boundary policy without embedding business terms in `ai_core`.


# AI Core Config-Driven Node Runtime v31

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


## v31 Fix

- Updated UI version label from v31 to v31.
- Added `/api/version`.
- Added no-cache headers for `/`.
- This avoids confusion when the browser or an old server process displays stale UI text.


## v31 Fix

- Fixed JavaScript syntax errors in `apps/web/index.html`.
- `/api/chat` now returns `run_id` immediately.
- Workflow execution starts in a background task.
- UI now displays `POST /api/chat` errors and SSE connection status.
- Added `.vscode/launch.json` and `.vscode/tasks.json`.


## v31 Update

- Added `runtime/generated/adapters/*.yaml`.
- `LLMJsonExecutor` calls a real configured provider instead of returning a placeholder.
- Provider config is generated at `runtime/configs/models/providers.yaml`.
- Supported provider protocols:
  - Ollama `/api/chat`
  - OpenAI Chat Completions
- If no provider is available, the workflow shows a clear `Node execution failed` message.
- `ai_core` still has no domain/task/business logic.


## v31 Update

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


## v31 Update

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


## v31 Fix

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


## v31 Update

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


## v31 Update

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
Any /v31/chat/completions compatible service
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


## v31 Update

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


## v31 Update

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


## v31 Update

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


## v31 Update

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


## v31 Update

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


## v31 Update

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


## v31 Update

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


## v31 Update

### Paused Human Interaction UI

Human interaction now behaves visually as a blocking checkpoint:

```text
node attempt 1
↓
Human Review: waiting
↓
user clicks Approve / Reject / Modify
↓
interaction is marked resolved
↓
workflow continues
```

### Retry Attempt Grouping

When `Reject & Retry` reruns the same node, the UI creates a new attempt card:

```text
intent_recognition / attempt 1
  └─ Human Review: resolved

intent_recognition / attempt 2
  └─ capability
  └─ provider
  └─ validation
```

This prevents new events from visually pushing the active human interaction upward inside the same node card.


## v31 Update

### Auto Schema Repair

When LLM JSON is structurally useful but the generated schema is too old or too narrow, runtime tries to repair the schema automatically before stopping for human recovery.

Example:

```text
confidence object is not of type number
```

Runtime can automatically evolve:

```json
"confidence": {"type": "number"}
```

into:

```json
"confidence": {
  "anyOf": [
    {"type": "number"},
    {"type": "object"}
  ]
}
```

Then it re-validates the same model output and continues the workflow if validation passes.

### Recovery order

```text
LLM JSON
↓
Schema validation
↓
If failed:
  auto schema repair
  ↓
  re-validation
  ↓
  continue if valid
↓
If still failed:
  Human recovery
```

Auto repair events are recorded in:

```text
runtime/knowledge/schema_auto_repair.jsonl
```


## v31 Update

### Sticky Blocking Interaction Panel

Human Review and API Key input are now displayed in a fixed bottom panel above the normal composer.

When a blocking interaction appears:

```text
workflowPaused = true
activeInteraction = event
normal input remains disabled
sticky interaction panel appears above composer
timeline receives a placeholder only
subsequent non-terminal events are buffered
```

When the user clicks:

```text
Approve
Reject & Retry
Modify JSON & Continue
Save Key & Continue
```

the UI:

```text
marks the interaction as resolved
hides the sticky panel
flushes buffered events
continues normal rendering
```

This prevents Human Review input from being pushed upward by later workflow logs.


## v31 Update

### Result Auto Repair

This version fixes cases where the model output is close to correct but omits required fields.

Example:

```text
JSON validation failed:
'intent_type' is a required property
```

Runtime now tries:

```text
schema validation failed
↓
result auto repair
  - find missing field from previous_results
  - find missing field from human feedback
  - otherwise use schema-safe default
↓
validate repaired result
↓
continue workflow if valid
↓
if still invalid, try schema auto repair
↓
if still invalid, Human Recovery
```

For example, if `intent_recognition` output omits `intent_type`, runtime can copy it from prior `input_parsing` result.

Repair log:

```text
runtime/knowledge/result_auto_repair.jsonl
```


## v31 Update

### Fixed Result Auto Repair Continuation

`RESULT_AUTO_REPAIRED` no longer leaves the node visually stuck.

Executor validation flow is now:

```text
validate original result
↓
if invalid, try result repair
↓
if repaired result validates:
  continue immediately
↓
else try schema repair
↓
if repaired schema validates:
  continue
↓
else human recovery
```

### Collapsed Human Interaction History

Resolved human interactions are now stored as collapsed details inside the node card instead of occupying a large visible area.

### UI Running State Fix

After a human interaction is resolved, the main composer stays disabled and shows `Thinking...` until the workflow actually completes/fails/cancels.


## v31 Update

### Fixed Schema Auto Repair Path Bug

Fixed:

```text
'str' object has no attribute 'parent'
```

Cause:

```text
SchemaAutoRepair.try_repair() received schema_path as str
but ConfigLoader.save_json() expects a Path-like object and uses .parent
```

Fix:

```python
self.loader.save_json(Path(schema_path), repaired)
```

Also adjusted the LLM JSON executor to pass `schema_path` as a Path object when calling schema auto repair.

This allows the workflow to continue after:

```text
RESULT_AUTO_REPAIRED
↓
SCHEMA_AUTO_REPAIRED
↓
re-validation
↓
continue workflow
```


## v31 Update

### Generic Runtime Execution Planner

The `execution` node no longer returns only:

```json
{
  "_status": "tool_call_ready"
}
```

It now reads:

```text
previous_results.workflow_planning.planned_steps
```

and generates a generic execution state:

```text
execution_steps
blocked_steps
human_interactions
missing_tools
safety_holds
summary
```

### No business logic in ai_core

The executor does not know weather, flight, booking, payment, etc.

It only interprets generic fields:

```text
step_id
step_type
required_capability
execution_ready
human_interaction
requires_human_confirmation
parameters.missing_required
```

### Missing Tool Spec Generation

If a required capability has no registered tool, runtime creates a missing implementation spec under:

```text
runtime/generated/tools/generated_<capability>.json
```

and registers it in:

```text
runtime/registry/tool_registry.json
```

### Execution behavior

```text
workflow_planning.planned_steps
↓
execution planner
↓
ready steps / blocked steps / human interactions / missing tools
```

## v31 Update

### Runtime Approval Memory
Approve is now positive memory and is saved to:
- runtime/datasets/approved_outputs.jsonl
- runtime/knowledge/success_patterns.jsonl
- runtime/knowledge/prompt_optimization_memory.jsonl

### Runtime Tool Builder Blueprint
Missing capability now generates:
- runtime/generated/tools/<tool_id>/tool.json
- runtime/generated/tools/<tool_id>/tool.py
- runtime/generated/tools/<tool_id>/README.md
- runtime/generated/tools/<tool_id>/test_input.json
- runtime/generated/tool_generation_requests/<request_id>.json

### Browser Automation Blueprint
Browser automation capability generates:
- runtime/generated/browser_blueprints/<blueprint_id>/blueprint.json
- runtime/generated/browser_blueprints/<blueprint_id>/tool.py
- runtime/generated/browser_blueprints/<blueprint_id>/README.md

Safety policy:
- prepare page allowed
- discover elements allowed
- preview action allowed
- irreversible click/submit requires explicit human confirmation

### Strong Model Escalation Policy
Strong models are used as Runtime Architect / Tool Builder for complex workflow, new capability, browser automation, and tool code generation.


## v31 Update

### Core Semantic Cleanup

Removed domain/semantic parsing from ai_core.

Fixed examples:

```text
browser_automation_blueprint.py
- removed hardcoded time regex
- removed direct URL/time/schedule semantic extraction
- now only writes runtime-provided structured metadata

escalation_policy.py
- removed business/domain/language keywords
- now uses generic runtime signals and policy config only

tool_blueprint_builder.py
- removed strategy inference from capability or natural language words
- strategy must come from runtime metadata
```

### New Rule

ai_core must not parse business language such as time expressions, attendance words, booking words, browser action semantics, or website-specific concepts.

Correct flow:

```text
LLM/runtime planning
↓
generates structured metadata
↓
ai_core stores/dispatches/validates generic metadata
```

### Scanner

Added:

```text
tools/scan_core_semantics.py
```

Run:

```bash
python tools/scan_core_semantics.py
```

This helps detect suspicious semantic/domain words inside ai_core.


## v31 Update

### Runtime Module Builder

ai_core can now generate generic runtime module blueprints when a required capability has no module/tool implementation.

This keeps ai_core generic:

```text
ai_core does not implement scheduler/notification/web_query logic directly.
ai_core generates module blueprints and code generation requests from structured runtime metadata.
```

Generated module package:

```text
runtime/generated/modules/<module_id>/
  module.json
  module.py
  README.md
  test_input.json
```

Generated code request:

```text
runtime/generated/module_generation_requests/<request_id>.json
```

Registry:

```text
runtime/registry/module_registry.json
```

### Generic Module Interface

Generated modules are expected to expose:

```text
validate_config(config)
health_check()
run(input_data)
```

### Example Flow

```text
User asks for scheduling/reminder/automation
↓
LLM/runtime planning produces structured capability + module metadata
↓
execution detects missing capability
↓
RuntimeModuleBuilder generates module blueprint
↓
strong model codegen request is created
↓
human review / safety review
↓
module registered and reused later
```

### Core Rule

ai_core must not parse natural language time, appointment, reminder, business actions, or domain semantics.

Those must be produced as structured metadata by runtime planning/LLM, then ai_core can generate and run generic modules.


## v31 Update

### Config-Driven Semantic Boundary Scanner

Removed hardcoded suspicious business/domain words from `tools/scan_core_semantics.py`.

New structure:

```text
ai_core/validation/semantic_boundary_scanner.py
  generic scanner engine only

tools/scan_core_semantics.py
  loads runtime policy

runtime/configs/policies/semantic_boundary.yaml
  project/runtime-generated rules
```

### Core Rule

`ai_core` must not contain business/domain forbidden words.

The scanner engine contains no domain knowledge. It only applies rules supplied by runtime config.

### Usage

```bash
python tools/scan_core_semantics.py
```

By default the policy is disabled:

```yaml
enabled: false
rules: []
```

### Policy Generation Request

Template added:

```text
runtime/generated/policies/semantic_boundary_policy_generation_request.json
```

This lets a stronger model generate a project-specific semantic boundary policy without embedding business terms in `ai_core`.


## v31 changes

- Unified executor interface: every executor implements `execute(...)`.
- Fixed `ToolCallExecutor` dispatch error from v30.
- Removed business/domain-specific safety examples from `ai_core` runtime code.
- Kept irreversible-action safety as generic runtime policy guidance.
- Preserved v30 principle: `ai_core` is a generic orchestration kernel; runtime-generated files hold business semantics.


# AI Core Config-Driven Node Runtime v31

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


## v31 Fix

- Updated UI version label from v31 to v31.
- Added `/api/version`.
- Added no-cache headers for `/`.
- This avoids confusion when the browser or an old server process displays stale UI text.


## v31 Fix

- Fixed JavaScript syntax errors in `apps/web/index.html`.
- `/api/chat` now returns `run_id` immediately.
- Workflow execution starts in a background task.
- UI now displays `POST /api/chat` errors and SSE connection status.
- Added `.vscode/launch.json` and `.vscode/tasks.json`.


## v31 Update

- Added `runtime/generated/adapters/*.yaml`.
- `LLMJsonExecutor` calls a real configured provider instead of returning a placeholder.
- Provider config is generated at `runtime/configs/models/providers.yaml`.
- Supported provider protocols:
  - Ollama `/api/chat`
  - OpenAI Chat Completions
- If no provider is available, the workflow shows a clear `Node execution failed` message.
- `ai_core` still has no domain/task/business logic.


## v31 Update

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


## v31 Update

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


## v31 Fix

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


## v31 Update

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


## v31 Update

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
Any /v31/chat/completions compatible service
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


## v31 Update

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


## v31 Update

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


## v31 Update

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


## v31 Update

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


## v31 Update

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


## v31 Update

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


## v31 Update

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


## v31 Update

### Paused Human Interaction UI

Human interaction now behaves visually as a blocking checkpoint:

```text
node attempt 1
↓
Human Review: waiting
↓
user clicks Approve / Reject / Modify
↓
interaction is marked resolved
↓
workflow continues
```

### Retry Attempt Grouping

When `Reject & Retry` reruns the same node, the UI creates a new attempt card:

```text
intent_recognition / attempt 1
  └─ Human Review: resolved

intent_recognition / attempt 2
  └─ capability
  └─ provider
  └─ validation
```

This prevents new events from visually pushing the active human interaction upward inside the same node card.


## v31 Update

### Auto Schema Repair

When LLM JSON is structurally useful but the generated schema is too old or too narrow, runtime tries to repair the schema automatically before stopping for human recovery.

Example:

```text
confidence object is not of type number
```

Runtime can automatically evolve:

```json
"confidence": {"type": "number"}
```

into:

```json
"confidence": {
  "anyOf": [
    {"type": "number"},
    {"type": "object"}
  ]
}
```

Then it re-validates the same model output and continues the workflow if validation passes.

### Recovery order

```text
LLM JSON
↓
Schema validation
↓
If failed:
  auto schema repair
  ↓
  re-validation
  ↓
  continue if valid
↓
If still failed:
  Human recovery
```

Auto repair events are recorded in:

```text
runtime/knowledge/schema_auto_repair.jsonl
```


## v31 Update

### Sticky Blocking Interaction Panel

Human Review and API Key input are now displayed in a fixed bottom panel above the normal composer.

When a blocking interaction appears:

```text
workflowPaused = true
activeInteraction = event
normal input remains disabled
sticky interaction panel appears above composer
timeline receives a placeholder only
subsequent non-terminal events are buffered
```

When the user clicks:

```text
Approve
Reject & Retry
Modify JSON & Continue
Save Key & Continue
```

the UI:

```text
marks the interaction as resolved
hides the sticky panel
flushes buffered events
continues normal rendering
```

This prevents Human Review input from being pushed upward by later workflow logs.


## v31 Update

### Result Auto Repair

This version fixes cases where the model output is close to correct but omits required fields.

Example:

```text
JSON validation failed:
'intent_type' is a required property
```

Runtime now tries:

```text
schema validation failed
↓
result auto repair
  - find missing field from previous_results
  - find missing field from human feedback
  - otherwise use schema-safe default
↓
validate repaired result
↓
continue workflow if valid
↓
if still invalid, try schema auto repair
↓
if still invalid, Human Recovery
```

For example, if `intent_recognition` output omits `intent_type`, runtime can copy it from prior `input_parsing` result.

Repair log:

```text
runtime/knowledge/result_auto_repair.jsonl
```


## v31 Update

### Fixed Result Auto Repair Continuation

`RESULT_AUTO_REPAIRED` no longer leaves the node visually stuck.

Executor validation flow is now:

```text
validate original result
↓
if invalid, try result repair
↓
if repaired result validates:
  continue immediately
↓
else try schema repair
↓
if repaired schema validates:
  continue
↓
else human recovery
```

### Collapsed Human Interaction History

Resolved human interactions are now stored as collapsed details inside the node card instead of occupying a large visible area.

### UI Running State Fix

After a human interaction is resolved, the main composer stays disabled and shows `Thinking...` until the workflow actually completes/fails/cancels.


## v31 Update

### Fixed Schema Auto Repair Path Bug

Fixed:

```text
'str' object has no attribute 'parent'
```

Cause:

```text
SchemaAutoRepair.try_repair() received schema_path as str
but ConfigLoader.save_json() expects a Path-like object and uses .parent
```

Fix:

```python
self.loader.save_json(Path(schema_path), repaired)
```

Also adjusted the LLM JSON executor to pass `schema_path` as a Path object when calling schema auto repair.

This allows the workflow to continue after:

```text
RESULT_AUTO_REPAIRED
↓
SCHEMA_AUTO_REPAIRED
↓
re-validation
↓
continue workflow
```


## v31 Update

### Generic Runtime Execution Planner

The `execution` node no longer returns only:

```json
{
  "_status": "tool_call_ready"
}
```

It now reads:

```text
previous_results.workflow_planning.planned_steps
```

and generates a generic execution state:

```text
execution_steps
blocked_steps
human_interactions
missing_tools
safety_holds
summary
```

### No business logic in ai_core

The executor does not know weather, flight, booking, payment, etc.

It only interprets generic fields:

```text
step_id
step_type
required_capability
execution_ready
human_interaction
requires_human_confirmation
parameters.missing_required
```

### Missing Tool Spec Generation

If a required capability has no registered tool, runtime creates a missing implementation spec under:

```text
runtime/generated/tools/generated_<capability>.json
```

and registers it in:

```text
runtime/registry/tool_registry.json
```

### Execution behavior

```text
workflow_planning.planned_steps
↓
execution planner
↓
ready steps / blocked steps / human interactions / missing tools
```

## v31 Update

### Runtime Approval Memory
Approve is now positive memory and is saved to:
- runtime/datasets/approved_outputs.jsonl
- runtime/knowledge/success_patterns.jsonl
- runtime/knowledge/prompt_optimization_memory.jsonl

### Runtime Tool Builder Blueprint
Missing capability now generates:
- runtime/generated/tools/<tool_id>/tool.json
- runtime/generated/tools/<tool_id>/tool.py
- runtime/generated/tools/<tool_id>/README.md
- runtime/generated/tools/<tool_id>/test_input.json
- runtime/generated/tool_generation_requests/<request_id>.json

### Browser Automation Blueprint
Browser automation capability generates:
- runtime/generated/browser_blueprints/<blueprint_id>/blueprint.json
- runtime/generated/browser_blueprints/<blueprint_id>/tool.py
- runtime/generated/browser_blueprints/<blueprint_id>/README.md

Safety policy:
- prepare page allowed
- discover elements allowed
- preview action allowed
- irreversible click/submit requires explicit human confirmation

### Strong Model Escalation Policy
Strong models are used as Runtime Architect / Tool Builder for complex workflow, new capability, browser automation, and tool code generation.


## v31 Update

### Core Semantic Cleanup

Removed domain/semantic parsing from ai_core.

Fixed examples:

```text
browser_automation_blueprint.py
- removed hardcoded time regex
- removed direct URL/time/schedule semantic extraction
- now only writes runtime-provided structured metadata

escalation_policy.py
- removed business/domain/language keywords
- now uses generic runtime signals and policy config only

tool_blueprint_builder.py
- removed strategy inference from capability or natural language words
- strategy must come from runtime metadata
```

### New Rule

ai_core must not parse business language such as time expressions, attendance words, booking words, browser action semantics, or website-specific concepts.

Correct flow:

```text
LLM/runtime planning
↓
generates structured metadata
↓
ai_core stores/dispatches/validates generic metadata
```

### Scanner

Added:

```text
tools/scan_core_semantics.py
```

Run:

```bash
python tools/scan_core_semantics.py
```

This helps detect suspicious semantic/domain words inside ai_core.


## v31 Update

### Runtime Module Builder

ai_core can now generate generic runtime module blueprints when a required capability has no module/tool implementation.

This keeps ai_core generic:

```text
ai_core does not implement scheduler/notification/web_query logic directly.
ai_core generates module blueprints and code generation requests from structured runtime metadata.
```

Generated module package:

```text
runtime/generated/modules/<module_id>/
  module.json
  module.py
  README.md
  test_input.json
```

Generated code request:

```text
runtime/generated/module_generation_requests/<request_id>.json
```

Registry:

```text
runtime/registry/module_registry.json
```

### Generic Module Interface

Generated modules are expected to expose:

```text
validate_config(config)
health_check()
run(input_data)
```

### Example Flow

```text
User asks for scheduling/reminder/automation
↓
LLM/runtime planning produces structured capability + module metadata
↓
execution detects missing capability
↓
RuntimeModuleBuilder generates module blueprint
↓
strong model codegen request is created
↓
human review / safety review
↓
module registered and reused later
```

### Core Rule

ai_core must not parse natural language time, appointment, reminder, business actions, or domain semantics.

Those must be produced as structured metadata by runtime planning/LLM, then ai_core can generate and run generic modules.


## v31 Update

### Config-Driven Semantic Boundary Scanner

Removed hardcoded suspicious business/domain words from `tools/scan_core_semantics.py`.

New structure:

```text
ai_core/validation/semantic_boundary_scanner.py
  generic scanner engine only

tools/scan_core_semantics.py
  loads runtime policy

runtime/configs/policies/semantic_boundary.yaml
  project/runtime-generated rules
```

### Core Rule

`ai_core` must not contain business/domain forbidden words.

The scanner engine contains no domain knowledge. It only applies rules supplied by runtime config.

### Usage

```bash
python tools/scan_core_semantics.py
```

By default the policy is disabled:

```yaml
enabled: false
rules: []
```

### Policy Generation Request

Template added:

```text
runtime/generated/policies/semantic_boundary_policy_generation_request.json
```

This lets a stronger model generate a project-specific semantic boundary policy without embedding business terms in `ai_core`.


## v31 changes

- Unified executor interface: every executor implements `execute(...)`.
- Fixed `ToolCallExecutor` dispatch error from v30.
- Removed business/domain-specific safety examples from `ai_core` runtime code.
- Kept irreversible-action safety as generic runtime policy guidance.
- Preserved v30 principle: `ai_core` is a generic orchestration kernel; runtime-generated files hold business semantics.


## v36 Zero Seed Runtime Generation

Concrete business tools are no longer shipped under `extensions/approved_tools`. `extensions` may contain only generic contracts/templates. Runtime-generated tool artifacts are installed into `runtime/generated/tools` and registered in `runtime/registry/tool_registry.json` during execution.


## v37 Real Runtime Generation

This version keeps `ai_core` provider-agnostic and domain-neutral.

- `ai_core` does not contain weather provider names, weather API URLs, or weather-specific routing.
- A workflow step may contain a `runtime_tool_generation` artifact produced by the runtime intelligence layer.
- `ai_core` validates, installs, registers, and executes that artifact generically.
- Generated tools must implement real HTTP/API behavior themselves, including retry, timeout, schema-compatible output, and error handling.
- The real network test is opt-in and contains no mock execution branch:

```bash
RUN_REAL_NETWORK_TEST=1 python3 scripts/smoke_test_weather_tool.py
```

Without `RUN_REAL_NETWORK_TEST=1`, the test exits before network execution to avoid accidental external calls.
