# Clean Runtime Notes

This package keeps task coordination data out of participant execution prompts.

## Agent-local prompt contract
Each participant receives only:

```json
{
  "participant_name": "...",
  "objective": "...",
  "context": {
    "relationship": "independent|dependent",
    "depends_on": [],
    "agent_parameters": {"values": {}},
    "available_peer_results": []
  }
}
```

`task_name`, `task_instruction`, task graph JSON, progress events, provider traces, and final synthesis policy are not included in participant LLM prompts.

## How execution can be selected without hardcoded business logic
The primary runtime should not decide by business keywords. The intended generic mechanism is:

1. LLM extracts an abstract intent and parameters.
2. LLM creates a minimal abstract step and required capability label.
3. Capability registry describes available execution primitives with generic metadata: input schema, output schema, evidence level, cost, latency, permissions, network needs, and confidence.
4. LLM/ranker chooses the best execution method by matching required capability + parameter coverage + evidence requirements.
5. The chosen method is validated by schema and evidence checks before the result is trusted.

This keeps domain behavior in runtime-generated contracts, tool specs, registry entries, and traces rather than hardcoded ai_core branches.
