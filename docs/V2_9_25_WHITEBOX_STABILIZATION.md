# v2.9.25 White-box stabilization notes

This version addresses the recurring failures observed in delegated weather/time tests by changing the runtime control flow rather than adding task-specific patches.

## Root causes confirmed

1. **Execution method drift**
   - Runtime-native temporal observations could still be reclassified as external information and routed to web evidence.
   - Fix: a final deterministic execution contract now detects timestamp-like runtime parameters and forces `runtime_generated_tool` / runtime-native execution.

2. **Evidence quality gate bypass**
   - External pages could produce many generic numeric fragments. Even when `answer_material_quality.passed=false`, those fragments were still allowed into final synthesis.
   - Fix: final synthesis now prefers contract-aligned source records from fetched source documents and selected evidence blocks. Unaligned generic numeric fragments from failed materialization are no longer recycled as final answer facts.

3. **Final answer looked like logs**
   - Delegated synthesis returned `Final Answer / Task / Agent(status)` style output.
   - Fix: delegated final synthesis now composes successful participant answers as a user-facing response and only briefly notes failed parts.

4. **Natural chat was treated as operation guidance**
   - Messages that were not create/execute/feedback commands still received operational instructions.
   - Fix: non-command messages go through `NaturalConversationService`, which first checks verified local knowledge and otherwise returns a normal conversational response.

5. **Knowledge base persistence was unclear**
   - Successful verified answers were not explicitly persisted as answer evidence.
   - Fix: output execution saves verified final answers into `runtime/knowledge/answer_results.jsonl` at runtime. This file is not included in source packages.

## White-box checks performed

The following checks were run against the provided runtime log sample:

- Weather evidence normalization produces aligned records for both requested target dates.
- Weather final synthesis no longer outputs coordinate/altitude fragments such as `Asia Tokyo UTC` or `Altitude`.
- Runtime-native temporal observation is forced to runtime execution instead of `api_call` / `web_search`.
- Non-command natural chat returns a conversation response instead of task operation guidance.
- Python compile check passed for `ai_core`, `auxiliary_brain`, and `apps`.

## Packaging policy

The package contains source/config/schema/docs only. It excludes:

- `__pycache__`
- `.pyc`
- runtime traces
- runtime checkpoints
- runtime generated results
- runtime secrets
- runtime cache/temp outputs
