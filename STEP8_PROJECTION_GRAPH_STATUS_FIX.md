# Step 8: Projection and Graph Runtime Status Fix

## Fixed

- Final answer projection now unwraps `{final_answer: ...}` payloads before UI delivery.
- Final answer compacting limit was expanded to avoid cutting valid user-facing content.
- Graph Runtime Viewer now overlays live run status from `agent_results`, `progress_events`, and `primary_runtime_events` instead of trusting only the static task graph.
- DAG nodes can now move from `pending` to `running`, `completed`, `failed`, or `skipped` while a run is executing.
- Runtime events panel now reads live progress events.
- Failed upstream nodes mark dependent pending nodes as skipped for visual correctness.

## Design constraints

- No domain or business vocabulary was added.
- No test-scenario data was added to source code.
- Status mapping is based only on generic structure: ids, dependencies, statuses, and runtime events.

## Verification

```bash
62 passed
```
