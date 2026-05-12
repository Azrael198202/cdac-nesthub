# AI Core Runtime v32 - Continuation Runtime

## Version Goal

v32 upgrades v31 from a workflow blocking detector into a continuation-aware runtime.

v31 could detect:

- missing tool implementation
- missing required information
- human confirmation holds

v32 adds the continuation layer:

```text
missing capability -> generate tool/module/codegen request -> pause for review
missing information -> ask user -> merge answers -> resume execution
human confirmation -> pause -> resume only after approval
```

## Core Principle

`ai_core` remains generic. It does not contain business task words or fixed task behavior.

Runtime-generated data may contain business semantics, but `ai_core` only uses structural fields such as:

- planned_steps
- parameters.known
- parameters.missing_required
- required_capabilities
- required_capability
- execution_ready
- requires_human_confirmation
- human_interactions
- missing_tools
- safety_holds

## New Modules

```text
ai_core/workflow/workflow_normalizer.py
ai_core/workflow/workflow_state_merger.py
ai_core/interaction/question_generator.py
ai_core/execution/continuation_engine.py
```

## Main Runtime Flow

```text
workflow_planning
↓
workflow_normalizer
↓
execution planner
↓
continuation_engine
↓
branch:
  missing info       -> HUMAN_INPUT_REQUIRED
  missing capability -> CAPABILITY_GENERATION_REQUESTED + HUMAN_REVIEW
  safety hold        -> HUMAN_REVIEW
  ready              -> execution_steps
```

## Resume Flow for Missing Information

The user can resume with:

```json
{
  "run_id": "...",
  "decision": "approve",
  "modified_result": {
    "answers": {
      "departure city": "Fukuoka",
      "number of passengers": "1",
      "flight class": "economy",
      "departure date": "2026-06-01"
    }
  }
}
```

The runtime will:

1. load checkpoint
2. merge answers into `workflow_planning.planned_steps[].parameters.known`
3. remove answered fields from `missing_required`
4. reset node index to the blocked node
5. resume execution

## Capability Mapping

If a step has no `required_capability`, v32 maps it from runtime-provided `required_capabilities` using generic token similarity.

Example:

```json
{
  "task_type": "weather.forecast.query",
  "required_capabilities": ["weather_api", "flight_booking_api"]
}
```

becomes:

```json
{
  "required_capability": "weather_api"
}
```

No business keyword is hardcoded in `ai_core`.

## Success Criteria

v32 is successful when:

1. Workflow planning output can be normalized.
2. Missing capabilities generate tool/module/codegen requests.
3. Missing required information generates a human input request.
4. User answers can be merged back into workflow state.
5. Runtime can resume from the blocked execution node.
6. Human confirmation remains required before sensitive execution.
