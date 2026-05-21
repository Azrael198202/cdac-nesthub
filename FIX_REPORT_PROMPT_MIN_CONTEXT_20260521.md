# Fix report: agent-local prompt minimization and source-only synthesis guard

## Root cause from traces.zip

The run did not fail because the mind-graph relation logic was wrong. The trace showed independent agent nodes, but the participant LLM prompts still included top-level task fields such as task_name, task_instruction, execution_policy, and expected_output. That made each agent re-process the whole task envelope instead of only its own objective and parameters.

Observed examples:

- input_parsing prompt included task_name/task_instruction even for an independent agent.
- intent_recognition prompt expanded to roughly 6.6k bytes.
- workflow_planning prompt expanded to roughly 11.5k bytes.
- workflow_planning provider request still contained roughly 2.4k chars and caused timeout or invalid JSON.
- final synthesis accepted source-only participant answers, so it returned only source URLs without verified answer material.

## Fixes

1. Agent execution payload is now local-only:
   - participant_name
   - objective
   - context.relationship
   - context.agent_parameters.values
   - strict JSON upstream summaries only when dependency exists

2. Removed from agent-local prompts:
   - task_name
   - task_instruction
   - community_id
   - task graph / mind graph
   - execution_policy
   - expected_output
   - participant count

3. workflow_planning and execution prompt inputs were reduced:
   - workflow_planning receives only objective, parameters, and compact parsed/intent facts
   - execution receives only the first compact step contract

4. workflow_planning model budget was reduced:
   - max_prompt_tokens: 520
   - max_schema_chars: 900
   - provider_timeout_seconds: 35
   - max_provider_attempts: 1
   - num_predict: 256

5. Final synthesis now rejects source-only participant answers.

6. Agent parameter contract prompt was improved to infer required parameters only and avoid optional preferences as required parameters.

## Validation

Passed:

- compileall
- smoke_fast_boot.py
- smoke_task_mind_graph.py
- smoke_prompt_minimal_parameters.py
- smoke_prompt_complexity_guard.py
- smoke_runtime_no_provider.py
- manual check: agent prompt no longer contains taskA or task_instruction

