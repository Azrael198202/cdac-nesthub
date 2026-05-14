# v68.2 Runtime No-Key Evidence Fallback Fix

## Fixed

1. Sandbox/static verification failure no longer forces a final `waiting_for_human_information` state when no-key evidence is available.
2. Optional API-key upgrade interactions are no longer treated as required human input.
3. Evidence direct answer fallback now reads nested `documentation_evidence.document.text_excerpt` and `source_search_result` content.
4. Generic web extraction date matching now supports dynamic ISO-date aliases, month/day aliases, and weekday aliases without hardcoding domain values.
5. Generic web extraction ignores relative date labels such as `date_expression` as evidence requirements and uses normalized parameters instead.
6. Final status is only `waiting_for_human_information` when an interaction is explicitly required.

## Expected behavior

For requests where location/date are already resolved and public web evidence exists:

- no API key is requested by default
- static LLM tool-generation errors fall back to deterministic web/evidence extraction
- the workflow should return an executable result or no-key evidence result instead of stopping with `The workflow is waiting...`

## Still generic

No domain-specific API/provider logic was added to `ai_core`.
