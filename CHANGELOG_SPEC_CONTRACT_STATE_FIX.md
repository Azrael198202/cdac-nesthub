# v21 Specification Contract + Runtime State Fix

## Main changes

1. Removed runtime format DSL repair path
   - Deleted `ai_core/runtime/common/format_dsl.py`.
   - Removed the runtime-side format token conversion path from the current capability acquisition flow.
   - The sandbox and validator no longer translate user-declared formats.

2. Moved field/type/format responsibility to Specification Contract
   - `CapabilitySpecificationContractCompiler` now preserves field types, defaults, schema formats, patterns, examples, and explicit `x-*` metadata.
   - Format/template fields are represented as generic value contracts.
   - Output bindings now carry a policy: generated code must satisfy the source contract; sandbox only verifies.

3. Code generation remains contract-driven
   - The generated implementation receives `specification_contract` before writing code.
   - The generator is instructed to implement the declared contract in the tool implementation, not rely on validator repair.

4. Runtime State API no longer spams 404 for stale run ids
   - `/api/runtime-state/runs/{run_id}` now returns a normal JSON payload with `ok=false` when the run no longer exists.
   - This avoids repeated server log `404 Not Found` messages when the UI has a stale selected run id.

5. Runtime State Console stale selection handling
   - If the selected run id is not in the run list, the UI clears the selection and selects the newest available run.
   - If a run detail response returns `ok=false`, the UI stops the stream, clears the detail panel, and prompts the user to select another run.

## Verification

- `python -m compileall -q ai_core auxiliary_brain apps tests` passed.
- `pytest -q` passed: 7 tests.
- Confirmed no remaining `format_dsl.py`, `TemporalFormat`, or `_directive_for_token` references.
