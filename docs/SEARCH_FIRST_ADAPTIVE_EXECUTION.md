# v2.9.23 Search-First Adaptive Execution

This version changes external-information execution from API-first to search-first.

## Execution order

1. Discover public web evidence.
2. Fetch/extract/reduce evidence with the Deep Web Research pipeline.
3. Run the evidence sufficiency gate.
4. If evidence is sufficient, stop and synthesize from normalized facts.
5. Only if evidence is insufficient, run API discovery / API escalation.
6. If API credentials are required, the UI may ask for the specific provider key or allow the user to skip that provider and continue fallback.

## Timeouts

Global execution timeout is raised to 180 seconds. Stage-level budgets are:

```yaml
execution_timeout_seconds: 180
stage_timeouts:
  web_discovery: 30
  web_search: 90
  extraction: 45
  evidence_validation: 20
  api_discovery: 15
  api_call: 30
  synthesis: 20
```

The stage budgets prevent one branch from consuming the whole run while still allowing web evidence extraction enough time to complete.

## Generic design

The implementation stays domain-neutral. It does not hard-code business keywords. Evidence quality is based on runtime parameters, target alignment, structured facts, source material, confidence, and sufficiency metadata.
