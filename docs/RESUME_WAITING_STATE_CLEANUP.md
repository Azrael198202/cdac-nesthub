# Resume Waiting State Cleanup

This version fixes the delegation state split that can happen after a durable resume.

## Problem

A run could accept required runtime input and continue execution, but the top-level delegation result still retained stale waiting fields such as `pending_action` and `missing_inputs`. The UI then continued to show a required-input prompt while the primary runtime was already executing a resumed node.

## Fix

When a durable resume request is accepted, the delegation runtime immediately transitions the run into an active resume state and clears the top-level waiting contract before calling the primary runtime checkpoint resume.

Participant-level paused payloads are preserved until the primary runtime returns the resumed result, because those payloads carry the checkpoint identity needed for the resume call.

## Expected behavior

- Required input dialog closes after submission.
- Top-level `pending_action` and `missing_inputs` are removed once resume starts.
- `current_stage` moves to active runtime stages as progress events arrive.
- If the resumed runtime still requires input, a new waiting contract is created from the latest primary-runtime response.
