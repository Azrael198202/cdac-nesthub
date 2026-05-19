# v2.9.7 Runtime Auto Repair and UI Recovery

This version separates two recovery paths:

1. **Automatic structural repair**
   - Used when a node result violates schema only because required structural fields are missing or null.
   - Repairs nested objects and array items recursively.
   - Does not invent domain facts.
   - Revalidates after repair before continuing.

2. **Human input recovery**
   - Used only when execution truly needs a human-provided value, such as a runtime access key or explicitly requested information.
   - The Studio UI now derives form fields from `pending_action` even when `missing_inputs` is empty.
   - The form opens automatically after a paused response that contains recoverable input requirements.

## Important behavior

A schema error such as a missing `next_action` inside a planned step should no longer stop the run immediately. The runtime first fills safe schema defaults and validates again. Only unrecoverable cases become a user-facing JSON correction request.

## Files changed

- `ai_core/validation/result_auto_repair.py`
- `auxiliary_brain/studio/service.py`
- `apps/web/agent_studio.html`
- `apps/api/server.py`
