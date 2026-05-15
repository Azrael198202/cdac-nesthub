# CDAC NestHub v70.29

## Focus

Stability fix for final answer synthesis and provider credential recovery.

## Changes

1. Added `StructuredFactNormalizer`.
2. Final answer synthesis now consumes normalized facts only.
3. Raw extraction traces such as `Matched Parameter`, `Descriptors`, and `Values` are blocked from final output.
4. Provider missing-secret errors now emit an `INTERACTION_REQUEST` so the UI can ask for an API key.
5. If the user does not provide a key, runtime falls back to deterministic synthesis from normalized evidence.
6. Prompt payload for final synthesis is reduced to normalized facts, not raw HTML or extraction traces.

## Verification

```text
compileall: OK
pytest v70.29: 3 passed
```
