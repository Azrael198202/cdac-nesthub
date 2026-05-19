# Interactive Missing Input Recovery

This version adds a generic human-input recovery loop for paused runtime execution.

## Behavior

When primary runtime pauses because a node needs additional information or because a generated JSON result failed schema validation, the Studio UI now opens a structured input dialog instead of only showing a paused state.

The dialog is generated from the runtime pending action and contains only generic field names and validation context. It does not use domain-specific rules.

## Flow

1. Runtime detects a pending action.
2. The pending action is persisted with the run result.
3. Studio displays a "Fill required input" action.
4. User fills the generated fields.
5. Studio posts `provided_inputs` to `/api/agent-studio/resume-run`.
6. Auxiliary runtime forwards the values to the primary runtime checkpoint.
7. Primary runtime merges the values into the paused node result or credential state.
8. Execution continues from the saved checkpoint.

## Supported pending actions

- `validation_recovery`
- `human_information_required`
- `secret_input`
- `optional_credential_choice`

## Design rule

The recovery mechanism is schema/path based. It must not contain business or domain keywords. Domain-specific behavior should be generated at runtime outside core.
