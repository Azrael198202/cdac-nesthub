# Runtime Capability Planner Model Contract

## Boundary

`ai_core` owns only the generic orchestration contract. It does not contain concrete capability implementations.

Runtime capability acquisition uses this sequence:

1. Capability Identity
2. Template Resolver
3. Blueprint Planner
4. Artifact Generator
5. Schema and sandbox validation
6. Verification run
7. Registry write

## Planner model resolution

The Blueprint Planner must record which engine was used.

Resolution priority:

1. `AI_CORE_CAPABILITY_PLANNER_MODEL`
2. `AI_CORE_SELECTED_LOCAL_MODEL`
3. `OLLAMA_MODEL`
4. `configs/model_selection.json` using `selected_local_model_id` or `initial_model_id`
5. neutral default only when no runtime selection exists

The planner result includes:

- `planner_engine`
- `model`
- `model_source`
- `fallback_used`
- `fallback_reason`
- `model_planner_attempt`

## Deterministic fallback

If the selected model is unavailable, times out, or returns non-JSON, the planner creates only a minimal structural blueprint.

The fallback does not generate code, protocol behavior, endpoints, credentials, or concrete runtime values. It creates a blueprint that lets the runtime-owned Artifact Generator produce a dry-run adapter candidate, which still must pass validation and registration gates.

Set `AI_CORE_DISABLE_CAPABILITY_BLUEPRINT_FALLBACK=1` to force hard failure for debugging.
