# Runtime Execution Convergence and Cost Policy

This version adds a domain-neutral runtime cost and convergence layer.

## Goals

- Avoid unbounded execution inside generated components.
- Avoid repeated expensive external model calls.
- Prefer deterministic repair before model escalation.
- Limit external evidence breadth before synthesis.
- Limit sandbox verification time.
- Keep runtime behavior configurable through policy and environment variables.

## New policy object

`global_policy.runtime_execution_policy.runtime_cost_policy`

Default values:

```json
{
  "enabled": true,
  "max_prompt_tokens": 6000,
  "max_provider_attempts": 1,
  "max_external_discovery_attempts": 1,
  "max_generated_component_attempts": 1,
  "max_evidence_pages": 2,
  "max_evidence_page_chars": 8000,
  "operation_timeout_seconds": 45,
  "sandbox_timeout_seconds": 25,
  "prefer_repair_before_model_escalation": true,
  "allow_paid_model_escalation": true
}
```

## Environment overrides

```bash
AI_CORE_TOKEN_SAVER_ENABLED=true
AI_CORE_MAX_PROMPT_TOKENS=6000
AI_CORE_MAX_PROVIDER_ATTEMPTS=1
AI_CORE_MAX_EXTERNAL_DISCOVERY_ATTEMPTS=1
AI_CORE_MAX_GENERATED_COMPONENT_ATTEMPTS=1
AI_CORE_MAX_EVIDENCE_PAGES=2
AI_CORE_MAX_EVIDENCE_PAGE_CHARS=8000
AI_CORE_OPERATION_TIMEOUT_SECONDS=45
AI_CORE_SANDBOX_TIMEOUT_SECONDS=25
AI_CORE_REPAIR_BEFORE_ESCALATION=true
AI_CORE_ALLOW_PAID_MODEL_ESCALATION=true
```

## Behavior changes

- LLM prompt budget is capped unless a lower adapter/provider budget is already configured.
- Provider route attempts are capped in normal mode.
- Schema result repair runs before paid model escalation when enabled.
- Evidence page fetching is capped by count and text length.
- Candidate adapter evaluation is capped and timeout guarded.
- Sandbox verification timeout is reduced and controlled by runtime policy.
- Execution step loop has a generic wall-clock guard.

No business/task-specific keywords are used by this layer.
