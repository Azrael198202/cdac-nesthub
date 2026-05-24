# cdac-nesthub 9.0

This package adds the session UI and the execution reuse layer.

## Main additions

- Left sidebar session UI: new session, session list, switch session, collapse sidebar.
- Session persistence: structured conversation turns, summaries, feedback, and local memory.
- Execution reuse registry:
  - saves successful task / agent / artifact execution assets;
  - reuses saved task assets on later executions;
  - bypasses planning when a reusable artifact is available;
  - asks only for missing runtime parameters when a saved parameter schema exists;
  - exposes `context_trace` so the UI can confirm whether task registry, artifact registry, LLM, or planning was used.
- Short answer cache for ephemeral chat that should not enter long-term memory.
- Runtime reset script for clean UI testing.

## Reset local test data

```bash
python scripts/reset_runtime_data.py --yes
```

To also remove runtime-generated artifacts, traces, checkpoints, and deliveries:

```bash
python scripts/reset_runtime_data.py --yes --include-runtime-generated
```

## Confirm reuse behavior

After a task succeeds once, execute the same task again. The response should include `context_trace` similar to:

```json
{
  "task_registry": true,
  "artifact_registry": true,
  "planning_used": false,
  "llm_used": false
}
```

For LLM-generation agents, the second execution should reuse the saved task and parameter contract. It may still call the LLM to generate the final answer, but it should not recreate the agent or re-plan the task.
