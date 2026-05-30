# Verification: Task Parameter Binding and Approval Policy

## Issue 1: Task parameters were provided but UI still asked again

Root cause:
- Runtime parameter extraction scanned the full task text with a broad regex.
- Section headers such as `Parameters for Weather Agent:` were incorrectly parsed as values such as `Agent: ...`.
- Step-level values were not reliably bound to the owning participant.

Fix:
- Replaced broad extraction with line-level assignment parsing.
- Added step-scoped parameter extraction from planned task fragments.
- Added participant-scoped keys such as `<participant_id>.<name>` and `<participant name>.<name>`.
- Execution-time preflight rehydrates step-scoped parameters from the task graph before missing-parameter detection.

Verified examples:
- `location: Fukuoka, Japan`
- `date: tomorrow`
- `to: ying.hahn@gmail.com`
- `subject: Weather Forecast`
- `body: {{Step2.final_answer}}`

Expected behavior:
- If values are already written in the task, the UI should not ask for them again.
- If values are missing, the existing input form is still shown.

## Issue 2: Confirmation should support future auto-confirm after explicit approval

Fix:
- Kept `Confirm execution` as the explicit approval label.
- Added an optional checkbox: `Do not ask again for this approved agent/tool`.
- When the user confirms and checks this option, a trust record is stored under runtime policy storage.
- Future executions for the same participant/tool can skip the confirmation prompt.

Safety:
- First execution still requires explicit confirmation.
- Auto-confirm is only enabled after the user explicitly chooses it.
- Existing Agent/Task parameter collection remains unchanged.
