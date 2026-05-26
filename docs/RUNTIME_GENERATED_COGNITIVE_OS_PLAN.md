# Runtime-Generated Cognitive Operating System Plan

## Core Principle

`ai_core` is not a place for business/domain/task implementations. It is the generic runtime brain that understands user intent, analyzes available capability contracts, generates runtime execution plans, schedules graph execution, validates results, and routes repair.

Concrete behavior must be generated, supplied, or resolved at runtime through artifacts, tools, skills, providers, APIs, local knowledge, web evidence, CLI commands, or LLM synthesis. The source package should remain domain-neutral and must not contain scenario-specific shortcuts.

## Target Architecture

The runtime should treat every executable unit as a capability node. A capability node may be backed by one or more execution forms:

- existing registered tool
- uploaded artifact
- runtime-generated code
- runtime-generated shell/CLI command
- web search or browser collection
- local knowledge/RAG retrieval
- generated or discovered API client
- external skill
- LLM synthesis
- document/file generation
- composed multi-step flow

The runtime decides the composition from user intent, context, environment, policy, and available contracts. It must not assume that execution always means running code.

## Model Strategy

The system must support different models for different cognitive stages while keeping output behavior model-invariant.

### Principles

1. Small local models should handle lightweight JSON stages such as input parsing, simple intent recognition, requirement detection, and capability classification.
2. Medium models should handle workflow/action planning, repair planning, and graph synthesis when deterministic contracts are insufficient.
3. Large/API models should be reserved for high-risk or high-complexity generation such as complex code generation, deep synthesis, and ambiguous repair.
4. Deterministic runtime checks should replace LLM calls whenever the result can be derived from schema, graph state, artifact contract, or environment state.
5. Every LLM output must pass schema/semantic validation so changing from local model to large/API model does not change the runtime contract.
6. Prompts must be stage-specific and minimal. Do not send complete runtime history to every stage.

## Phase 1: Runtime Artifact / Capability Contract Stability

### Goal

Uploaded or runtime-generated artifacts must produce stable runtime contracts before execution.

A contract should include:

- input schema
- output schema when available
- required parameters
- optional parameters
- default values
- execution entrypoint
- execution readiness
- missing parameter request fields
- evidence path
- sandbox policy

### Current Work

Phase 1 focuses on generic artifact contract handling. The source code only contains generic contract inspection. Concrete contracts are emitted under `runtime/generated/contracts/<run_id>/` during execution.

### Success Criteria

1. A Python artifact with `def run():` requires no parameters.
2. A Python artifact with `def run(value: str):` requests `value` before execution.
3. A Python artifact with `def run(value: str = "x"):` treats `value` as optional and records the default.
4. A Python artifact with `def run(payload):` is treated as single-object payload style and does not incorrectly require a field named `payload`.
5. Existing concrete parameter values satisfy the contract without asking the user again.
6. Placeholder values such as `missing`, `unknown`, `todo`, or `{value}` do not satisfy required parameters.
7. The contract is runtime-generated, auditable, and not stored as fixed source logic.

### User Verification Cases

#### Case 1: No-parameter artifact

Upload an artifact containing:

```python
def run():
    return {"answer_material": "ok"}
```

Expected:

- no parameter UI request
- execution preparation status is `prepared`
- execution runs the artifact
- final answer uses the real artifact result

#### Case 2: Required-parameter artifact

Upload an artifact containing:

```python
def run(value: str):
    return {"answer_material": value}
```

Expected:

- UI asks for `value`
- graph pauses until the value is provided
- after value submission, execution resumes

#### Case 3: Optional-parameter artifact

Upload an artifact containing:

```python
def run(value: str = "default"):
    return {"answer_material": value}
```

Expected:

- no blocking missing-parameter request
- contract records `value` as optional
- contract records the default value

## Phase 2: Execution State and Graph Stability

### Goal

Graph execution must be deterministic and auditable.

### Required Behavior

- downstream nodes must not show `completed` when upstream failed
- each edge must show output binding from source to target
- skipped, failed, waiting, and completed states must be distinct
- final synthesis may only use verified result material

### User Verification Case

Create a three-step task where step 1 intentionally fails and steps 2 and 3 depend on it.

Expected:

- step 1 failed
- step 2 skipped or failed by dependency
- step 3 skipped or failed by dependency
- final answer does not treat the error as normal content

## Phase 3: Runtime Capability Composition

### Goal

Runtime should unify code, web, RAG, API, CLI, tool, skill, browser, and LLM execution as capability nodes.

### Required Behavior

- runtime chooses execution form from intent, policy, environment, and contracts
- web/API/RAG/code/tool/CLI are not hardwired into business paths
- missing capability can trigger runtime generation, registration, validation, and reuse

### User Verification Case

Request: search current external information, summarize it, and generate a local Markdown file.

Expected graph:

1. external evidence collection
2. evidence normalization
3. synthesis
4. file generation
5. file verification

## Phase 4: Cognitive Validation

### Goal

Completed status is not enough. The system must validate whether the user goal was satisfied.

### Required Behavior

- language constraint validation
- format validation
- count/length validation
- evidence/source validation
- file existence validation
- output coverage validation

### User Verification Case

Request: write a Japanese 300-character explanation containing transport and season information.

Expected:

- language check passes
- approximate length check passes
- required content coverage passes
- repair is triggered if any constraint fails

## Phase 5: Self Repair and Runtime Learning

### Goal

Failures should produce runtime repair plans and improve future execution.

### Required Behavior

- classify failure type
- generate repair plan
- rerun only affected graph segments
- store successful strategy as runtime learning
- prefer learned strategy for similar future requests

## Current Priority

Before moving to the next version, stabilize Phase 1 and Phase 2:

1. artifact/capability contract stability
2. graph execution state integrity
3. prompt slimming and model stage routing
4. verified-result-only final synthesis
5. user-visible validation cases

