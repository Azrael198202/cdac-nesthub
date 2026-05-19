# v2.9.19 Secret State and Timeout Finalization Fix

This version fixes two runtime stability problems observed after API-only execution was enabled.

## Fixes

1. Credential state cleanup
   - When a secret is submitted during durable resume, the primary-runtime state now clears stale `pending_action`, `missing_inputs`, and waiting markers immediately.
   - Completed participant payloads are sanitized so old `requires_key` placeholders cannot keep the UI input dialog open.
   - `SecretStore` now mirrors saved credentials into an in-memory cache and `os.environ`, so subsequent participants in the same process can reuse the same key without asking again.

2. Duplicate key prompt prevention
   - The provider router checks the canonical secret store before emitting another credential request.
   - If the key is already available, it skips the UI prompt path.

3. Execution timeout finalization
   - Primary-runtime execution and durable resume are wrapped by a timeout finalizer.
   - If a node or sandbox subtask does not return, the run is finalized as failed instead of remaining forever in `running`.
   - A `runtime_timeout_finalizer` result is written for diagnosis.

## Packaging

The zip excludes runtime outputs, checkpoints, traces, cache, secrets, `__pycache__`, and `.pyc` files.
