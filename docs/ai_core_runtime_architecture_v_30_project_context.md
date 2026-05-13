# AI Core Runtime Architecture v30

## 1. Project Overview

This project is a fully config-driven AI Runtime Operating System.

Core philosophy:

```text
ai_core must remain completely generic.
```

The system is designed so that:

- ai_core contains NO business/domain logic
- ai_core contains NO project-specific workflows
- ai_core contains NO hardcoded scheduling semantics
- ai_core contains NO fixed automation behaviors
- ai_core contains NO fixed tool/business keywords

Instead:

```text
All business semantics are generated at runtime.
```

The runtime layer is responsible for:

- intent understanding
- semantic interpretation
- workflow generation
- capability planning
- tool generation
- module generation
- prompt optimization
- runtime learning
- correction memory
- approval memory
- policy generation

---

# 2. Architecture Philosophy

## 2.1 Core Rule

```text
ai_core = generic runtime orchestration engine
runtime = generated intelligence layer
```

Meaning:

```text
ai_core:
  only executes generic orchestration

runtime:
  contains generated logic/config/workflows/tools/modules/policies
```

---

# 3. High-Level Runtime Flow

```text
User Input
↓
Intent Understanding
↓
Runtime Semantic Planning
↓
Workflow Generation
↓
Capability Resolution
↓
Tool / Module Generation
↓
Human Review
↓
Execution
↓
Runtime Learning
↓
Correction Memory
↓
Approval Memory
↓
Prompt Optimization
```

---

# 4. ai_core Responsibilities

ai_core ONLY handles generic orchestration.

## ai_core Responsibilities

### Generic Runtime Execution

```text
- node execution
- workflow dispatch
- state management
- checkpoint management
- event streaming
- schema validation
- runtime registry loading
- runtime config loading
- runtime module loading
```

### Generic Validation

```text
- JSON validation
- schema validation
- semantic boundary scanning
- runtime policy execution
```

### Generic Runtime Builders

```text
- tool blueprint generation
- module blueprint generation
- code generation request generation
- browser blueprint persistence
```

### Generic Learning

```text
- correction memory
- approval memory
- prompt reinforcement
- runtime datasets
```

---

# 5. What ai_core MUST NOT contain

## ai_core MUST NOT contain:

```text
- business words
- domain concepts
- fixed schedules
- attendance logic
- booking logic
- weather logic
- browser semantic logic
- login flow assumptions
- time understanding logic
- appointment semantics
- reminder semantics
```

Examples NOT allowed inside ai_core:

```python
"flight"
"weather"
"booking"
"attendance"
"weekday"
```

Also NOT allowed:

```python
re.finditer(r"(\d{1,2})[:点時](\d{0,2})")
```

Reason:

```text
Time understanding is business semantics.
```

Time semantics must be generated dynamically by runtime planning.

---

# 6. Runtime Layer Responsibilities

The runtime layer contains generated intelligence.

## Runtime Responsibilities

```text
- semantic interpretation
- business understanding
- workflow generation
- tool strategy generation
- module strategy generation
- browser automation understanding
- schedule understanding
- project policies
- capability metadata
- generated prompts
- generated schemas
```

---

# 7. Runtime Directory Structure

```text
runtime/
├── configs/
│   ├── models/
│   ├── capabilities/
│   ├── workflows/
│   ├── policies/
│   └── environment/
│
├── generated/
│   ├── prompts/
│   ├── schemas/
│   ├── workflows/
│   ├── tools/
│   ├── modules/
│   ├── browser_blueprints/
│   ├── module_generation_requests/
│   ├── tool_generation_requests/
│   └── policies/
│
├── datasets/
│   ├── corrections.jsonl
│   ├── approved_outputs.jsonl
│   ├── finetune.jsonl
│   └── eval_cases.jsonl
│
├── knowledge/
│   ├── success_patterns.jsonl
│   └── prompt_optimization_memory.jsonl
│
├── registry/
│   ├── tool_registry.json
│   ├── module_registry.json
│   └── provider_registry.json
│
├── traces/
├── checkpoints/
└── logs/
```

---

# 8. Config-Driven Node Runtime

## Philosophy

```text
Node behavior is NOT hardcoded.
```

Everything is runtime generated:

```text
- prompts
- schemas
- adapters
- workflows
- node configs
```

---

# 9. Workflow Structure

Example runtime workflow:

```text
input_parsing
↓
intent_recognition
↓
context_awareness
↓
workflow_planning
↓
execution
↓
feedback_learning
↓
output
```

Each node is runtime-configured.

---

# 10. Runtime Learning

## Runtime Learning Philosophy

The system continuously learns from:

```text
- validation failures
- human corrections
- approved outputs
- retry feedback
```

---

# 11. Correction Memory

When user selects:

```text
Modify JSON & Continue
```

Runtime automatically stores:

```json
{
  "node": "input_parsing",
  "original_output": {},
  "human_corrected_output": {},
  "feedback": "tasks should be structured objects"
}
```

Stored in:

```text
runtime/datasets/corrections.jsonl
```

Used later for:

```text
prompt reinforcement
↓
similar task optimization
↓
automatic output improvement
```

---

# 12. Approval Memory

When user selects:

```text
Approve
```

The runtime stores:

```text
approved_outputs.jsonl
success_patterns.jsonl
prompt_optimization_memory.jsonl
```

Purpose:

```text
Positive learning memory.
```

Meaning:

```text
This structure was accepted by humans.
```

Future prompts are reinforced with approved patterns.

---

# 13. Human Review System

## Human Review Philosophy

Irreversible actions must require confirmation.

Examples:

```text
- purchases
- bookings
- attendance submission
- form submission
- browser submit/click
```

The runtime can:

```text
- prepare
- navigate
- discover
- analyze
```

But irreversible actions require confirmation.

---

# 14. Runtime Tool Builder

## Tool Builder Philosophy

If capability is missing:

```text
Runtime generates tool blueprint.
```

NOT:

```text
Hardcoded tools in ai_core.
```

Generated structure:

```text
runtime/generated/tools/<tool_id>/
```

Includes:

```text
tool.json
tool.py
README.md
test_input.json
```

---

# 15. Runtime Module Builder

## Module Builder Philosophy

If capability requires reusable runtime behavior:

```text
Runtime generates module blueprint.
```

Examples:

```text
- scheduler
- notification
- web query
- browser automation
- file generation
```

BUT:

```text
ai_core does NOT implement them directly.
```

Generated under:

```text
runtime/generated/modules/
```

---

# 16. Strong Model Escalation

## Why escalation exists

Local models may fail for:

```text
- workflow architecture
- tool design
- module design
- code generation
- browser automation planning
- schema generation
```

So runtime supports:

```text
local model
↓
failure / low confidence
↓
escalation policy
↓
strong external model
```

Examples:

```text
OpenAI
Claude
Gemini
```

But:

```text
Escalation logic itself must remain generic.
```

No business keywords inside ai_core.

---

# 17. Semantic Boundary System

## Goal

Prevent business/domain leakage into ai_core.

## Structure

```text
ai_core/validation/semantic_boundary_scanner.py
```

Contains:

```text
ONLY generic scanner engine
```

Rules are NOT embedded.

Rules come from:

```text
runtime/configs/policies/semantic_boundary.yaml
```

---

# 18. Browser Automation Philosophy

## Important Principle

ai_core does NOT understand browser business semantics.

It does NOT know:

```text
- attendance
- login meaning
- reservation meaning
- schedule meaning
```

Instead:

```text
Runtime planning
↓
Generates structured browser blueprint metadata
↓
ai_core stores/loads/dispatches it
```

---

# 19. Time / Reminder / Schedule Philosophy

## Critical Rule

ai_core does NOT parse time language.

NOT allowed:

```python
"weekday"
"8:30"
"tomorrow"
```

inside ai_core business logic.

Correct flow:

```text
User Input
↓
LLM/runtime semantic understanding
↓
Structured schedule metadata
↓
ai_core generic execution
```

Example generated metadata:

```json
{
  "schedule": {
    "type": "rrule",
    "rrule": "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR",
    "time": "08:30"
  }
}
```

ai_core only executes:

```text
- load metadata
- compare time
- trigger workflow
```

---

# 20. Generic Runtime Scheduler (Future)

Scheduler itself should be generated as runtime module.

NOT hardcoded.

Generated module interface:

```text
validate_config()
health_check()
run()
```

---

# 21. Runtime Generated Policies

Policies are runtime-generated.

Examples:

```text
semantic boundary policy
security policy
approval policy
capability policy
```

Generated by:

```text
LLM
project context
human review
runtime generation
```

---

# 22. UI Philosophy

The UI is event-driven.

Supports:

```text
- streaming events
- thinking states
- human review cards
- collapsible hierarchy
- loading indicators
- runtime progress
- retry flows
```

Human review must interrupt execution flow.

Execution resumes only after:

```text
Approve
Reject & Retry
Modify JSON & Continue
```

---

# 23. Runtime Safety Model

## Core Safety Principles

```text
- no irreversible action without confirmation
- no secret logging
- generated code requires review
- browser automation requires approval
- module activation requires approval
```

---

# 24. Long-Term Vision

## Final Goal

A self-evolving AI Runtime OS.

Capabilities:

```text
- generate workflows
- generate tools
- generate modules
- generate policies
- learn from corrections
- learn from approvals
- optimize prompts
- escalate to stronger models
- reuse successful patterns
```

WITHOUT:

```text
hardcoded business systems inside ai_core
```

---

# 25. Current Version Status

## Current Runtime Version

```text
v30
```

## Current Major Features

```text
✔ Config-driven node runtime
✔ Runtime learning
✔ Approval memory
✔ Correction memory
✔ Tool blueprint generation
✔ Module blueprint generation
✔ Browser blueprint persistence
✔ Runtime module registry
✔ Strong model escalation
✔ Semantic boundary scanner
✔ Runtime-generated policy structure
✔ Human review system
✔ Event streaming UI
✔ Generic runtime architecture
```

---

# 26. Future Roadmap

## Planned Next Steps

```text
- runtime-generated scheduler module
- runtime-generated notification module
- dynamic capability marketplace
- auto-generated runtime APIs
- runtime-generated tests
- runtime-generated deployment manifests
- runtime-generated monitoring
- runtime-generated CI/CD
- vector memory optimization
- automatic model routing optimization
```

---

# 27. Final Architectural Principle

```text
ai_core should eventually become:

A minimal generic orchestration kernel.
```

Everything else:

```text
- business logic
- workflows
- tools
- modules
- schedules
- browser automation
- semantic policies
- prompts
- schemas
```

must be runtime generated.

