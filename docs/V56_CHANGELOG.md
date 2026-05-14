# v56 Runtime JSON State Repair

## Goal

Improve runtime-generated JSON quality across intent recognition, workflow planning, and execution without adding domain-specific logic to `ai_core`.

## Added

- Generic `ExecutionStateRepair` before tool execution.
- Runtime-configured optional refinement field policy.
- Runtime prompt updates for:
  - `intent_recognition`
  - `workflow_planning`
  - `execution_state_repair`
- Stronger generated JSON schemas for intent and workflow planning.
- Smoke test for over-blocked workflow repair.

## Runtime Behavior

The runtime now normalizes and repairs workflow state before execution:

1. Normalize workflow JSON.
2. Recover empty planning result if needed.
3. Repair over-blocked execution state.
4. Validate structural state.
5. Execute, discover capability, or request human input.

## Important Design Rule

`ai_core` remains generic. Domain-specific terms, provider names, task examples, and business assumptions must stay in runtime-generated files, runtime configuration, traces, or generated artifacts.

## Validation

- `py_compile`: OK
- `smoke_test.py`: OK
- `smoke_test_v54.py`: OK
- `smoke_test_v55.py`: OK
- `smoke_test_v56.py`: OK
- JSON schema smoke validation: OK
