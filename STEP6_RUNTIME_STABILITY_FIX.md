# Step 6 Runtime Stability Fix

This update fixes the regression where a generated dataflow step could accept a generic model refusal as a successful final answer.

## Changes

- Generated dataflow steps now stop early when declared upstream outputs are missing.
- Generic refusal / environment-unavailable text is rejected as result material.
- Dataflow LLM prompt is shorter and uses a smaller output budget.
- JSON repair retry is disabled for lean dataflow steps to avoid extra model calls.
- Raw text fallback remains allowed only when it contains public result material.
- Final projection steps with a single upstream output continue without another model call.

## Verification

```bash
58 passed
```
