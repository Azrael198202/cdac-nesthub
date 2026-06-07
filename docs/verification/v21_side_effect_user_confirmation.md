# v21 Side Effect Verification + User Confirmation

v21 keeps Verification Brain generic and evidence-first. It does not pretend that every external side effect can be proven automatically.

## Side-effect states

- `verified`: runtime could verify the result locally or through a declared read-back verifier.
- `failed`: tool/status/artifact/read-back verification failed.
- `accepted_pending_user_confirmation`: the side effect was accepted by the capability, but the runtime cannot prove the external world state.
- `not_verifiable`: the capability explicitly declares no automatic verifier.

## Default behavior

For `accepted_pending_user_confirmation` and `not_verifiable`, the task is allowed to continue. The runtime records a confirmation request under:

```text
runtime/generated/side_effect_confirmations/
```

The default assumption is:

```text
success_until_user_reports_failure
```

## User feedback loop

If the user later reports that the side effect did not actually work, the runtime records the feedback and generates a failure report with:

```text
failure_class = user_confirmed_side_effect_failure
```

This report is visible through the existing failure report APIs and can be used by repair_brain as the next repair trigger.

## APIs

```text
GET  /api/verification/side-effect-confirmations
POST /api/verification/side-effect-confirmations/{confirmation_id}/feedback
```

Feedback payload:

```json
{
  "outcome": "failed",
  "note": "External result was not observed."
}
```

## Generic design

No business-specific words are used in the verifier. It only works from structural runtime facts: participant id, tool id, result status, artifact references, declared verification mode, and user feedback.
