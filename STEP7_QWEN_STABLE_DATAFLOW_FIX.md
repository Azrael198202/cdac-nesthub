# Step 7: Stable dataflow execution for local small models

## Fixed issue

The previous dataflow execution could produce a truncated JSON wrapper when the local model reached its generation budget. The UI then displayed partial JSON such as `{"final_answer":"...` instead of a complete user-facing answer.

## Changes

- Dataflow steps now ask the model for plain user-facing text instead of a JSON wrapper.
- The completion budget for dataflow text transformation was increased while keeping the prompt compact.
- Returned text is normalized before being accepted, so accidental `final_answer` JSON wrappers are unwrapped.
- Incomplete JSON wrappers from lenient fallback are not shown directly to the user.
- The final projection step can still bypass the model when it only needs to return the previous step result.
- No domain-specific task vocabulary was added to the core logic.

## Verification

```bash
60 passed
```
