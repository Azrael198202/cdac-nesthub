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


说明 VS Code 正在用 Homebrew 的 Python 3.14，而不是你安装依赖的环境。

先在项目目录执行：

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt

然后 VS Code 里选择解释器：

Cmd + Shift + P
Python: Select Interpreter
选择：
./.venv/bin/python

