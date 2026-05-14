# v65 Stage-Minimal JSON Runtime

## Goal

v65 tightens the runtime JSON contract for each orchestration stage so every node only outputs data owned by that stage.

## Main changes

1. `input_parsing` no longer outputs executable tasks, workflow plans, capabilities, tool choices, API choices, or provider choices.
2. `intent_recognition` no longer outputs executable tasks, workflow plans, capabilities, tool choices, API choices, or provider choices.
3. `workflow_planning` is the first stage that may create executable `planned_steps`.
4. `workflow_planning` may use generic capability names only. Concrete tools, APIs, providers, repos, libraries, and implementation files are resolved later by execution/capability resolution.
5. Runtime template evolution no longer upgrades early-stage `tasks` into executable task objects.
6. Schema auto-repair protects `input_parsing` and `intent_recognition` from reintroducing top-level `tasks`.

## Stage responsibilities

### input_parsing

Allowed:
- `language`
- `original_input`
- `parsed_entities`
- `semantic_modifiers`
- `constraints`
- `temporal_expressions`
- `missing_information`
- `safety_notes`

Forbidden:
- `tasks`
- `planned_steps`
- `required_capabilities`
- tool/API/provider choices
- execution decisions

### intent_recognition

Allowed:
- `intent_type`
- `intent_summary`
- `normalized_intent`
- `confidence`
- `human_review`

Forbidden:
- `tasks`
- `planned_steps`
- `required_capabilities`
- tool/API/provider choices
- execution decisions

### workflow_planning

Allowed:
- `planned_steps`
- `blocking_missing_information`
- `required_capabilities`
- `human_interaction`

Rules:
- `planned_steps` must be executable objects, not strings.
- Use generic capabilities only.
- Do not select concrete implementation.
- Copy normalized entities from upstream nodes.

## Validation

```text
compileall: OK
smoke_test_v64: OK
smoke_test_v65: OK
```
