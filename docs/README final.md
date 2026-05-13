# AI Core Runtime

A provider-agnostic, domain-neutral, self-evolving AI orchestration runtime.

---

# Overview

AI Core Runtime is designed as a dynamic execution operating system for AI workflows.

Unlike traditional AI systems that hardcode:

* providers
* APIs
* business logic
* workflow semantics
* tool routing
* domain behavior

inside the core engine,

AI Core Runtime separates:

```text
Stable Core Runtime
+
Dynamic Runtime Intelligence
```

The core acts only as:

```text
Interpreter
Executor
Validator
Coordinator
```

All business logic, workflow behavior, prompts, tools, schemas, and capabilities are dynamically generated and loaded at runtime.

---

# Core Design Principles

## 1. ai_core Must Remain Generic

`ai_core` must never contain:

* weather logic
* scheduling logic
* booking logic
* SDLC logic
* browser semantics
* family/accounting logic
* task-specific parsing
* provider-specific assumptions

The core only understands:

```text
workflow
capability
execution
validation
approval
memory
runtime events
```

---

## 2. Runtime Generates Intelligence

The runtime dynamically generates:

```text
runtime/generated/
  nodes/
  prompts/
  workflows/
  schemas/
  tools/
  modules/
  adapters/
  policies/
```

The runtime evolves continuously while the core remains stable.

---

## 3. Provider Agnostic Architecture

The runtime supports multiple providers dynamically:

* Ollama
* OpenAI
* LM Studio
* vLLM
* future providers

Providers are configured through runtime configuration only.

No provider logic is embedded in ai_core.

---

## 4. Human-in-the-Loop Runtime

Critical execution supports:

* approve
* reject
* modify
* retry
* resume

The runtime can pause and continue workflows safely.

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
Validation
    ↓
Human Review (if required)
    ↓
Learning / Memory
    ↓
Output
```

---

# Runtime Architecture

```text
ai_core/
  execution/
  executors/
  validation/
  memory/
  workflow/
  runtime/

runtime/
  configs/
  generated/
  registry/
  knowledge/
  traces/
  checkpoints/
```

---

# Runtime Generated Components

## Nodes

```text
runtime/generated/nodes/*.yaml
```

Defines runtime execution behavior.

---

## Prompts

```text
runtime/generated/prompts/*.yaml
```

Prompt templates generated dynamically.

---

## Schemas

```text
runtime/generated/schemas/*.json
```

Output validation schemas.

---

## Tools

```text
runtime/generated/tools/
```

Generated runtime tools and adapters.

---

## Modules

```text
runtime/generated/modules/
```

Generated reusable runtime modules.

---

# Execution Model

The runtime executes workflows through generic executors.

Supported executor types:

```text
llm_json
tool_call
workflow_call
mcp_call
human_review
python_plugin
static_transform
```

Each executor implements:

```python
execute(...)
```

---

# Human Interaction Runtime

The runtime supports blocking human interaction.

Example flow:

```text
workflow running
↓
missing information detected
↓
human interaction request generated
↓
workflow paused
↓
user provides input
↓
workflow resumes
```

Supported interaction types:

* approval
* structured form input
* API key input
* JSON modification
* retry confirmation

---

# Validation System

The runtime validates all generated outputs through schemas.

Validation pipeline:

```text
LLM Output
↓
Schema Validation
↓
Result Auto Repair
↓
Schema Auto Repair
↓
Human Recovery
```

Auto-repair logs:

```text
runtime/knowledge/
  schema_auto_repair.jsonl
  result_auto_repair.jsonl
```

---

# Dynamic Capability System

The runtime can dynamically:

* generate tools
* generate modules
* install dependencies
* start services
* register providers
* pull models
* repair environments
* retry execution

---

# Semantic Boundary Rule

`ai_core` must not contain business/domain semantics.

Forbidden examples:

* schedule parsing
* booking parsing
* attendance parsing
* weather semantics
* browser action semantics

Correct flow:

```text
LLM/runtime planning
↓
structured metadata
↓
generic ai_core execution
```

---

# Semantic Boundary Scanner

Scanner:

```text
tools/scan_core_semantics.py
```

Policy:

```text
runtime/configs/policies/semantic_boundary.yaml
```

Purpose:

* detect forbidden domain logic
* keep ai_core generic
* enforce runtime-driven architecture

---

# Repository Structure

```text
project/
│
├─ ai_core/
├─ runtime/
│   ├─ configs/
│   ├─ generated/
│   ├─ registry/
│   ├─ knowledge/
│   ├─ traces/
│   └─ checkpoints/
│
├─ docs/
├─ scripts/
├─ tools/
├─ apps/
└─ tests/
```

---

# Startup

## Install

```bash
pip install -r requirements.txt
```

---

## Run

```bash
python main.py
```

---

## Open UI

```text
http://127.0.0.1:8000
```

---

# Smoke Test

```bash
python scripts/smoke_test.py
```

---

# Current Runtime Stage

```text
v38 = Human Interaction Runtime
```

Current capabilities:

* runtime-generated workflows
* runtime-generated tools
* dynamic capability resolution
* human interaction pause/resume
* provider-agnostic execution
* schema auto repair
* result auto repair
* workflow continuation
* runtime-generated interaction forms

---

# Next Direction

Planned evolution:

```text
v39+
  runtime semantic planning
  autonomous tool improvement
  capability marketplace
  distributed runtime execution
  self-optimizing workflow routing
```

---

# Core Philosophy

```text
Stable Core
Dynamic Runtime
Self-Evolving Capabilities
Human-Governed Intelligence
```

AI Core Runtime is not a chatbot framework.

It is a runtime operating system for dynamically evolving AI workflows.
