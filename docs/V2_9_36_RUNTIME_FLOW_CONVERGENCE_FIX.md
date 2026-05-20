# v2.9.36 Runtime Flow Convergence Fix

This release removes unstable fallback behavior instead of adding another domain-specific patch.

## Principles

- No business/domain-specific keywords or hard-coded domain logic in `ai_core`.
- Runtime-native contracts must not fall through to web/API evidence.
- External evidence must either produce verified material or return an investigation report.
- A source-only answer is not a valid participant result.
- Final delegated synthesis must not use failed/partial participant URLs as facts.

## Key changes

1. Evidence branch now returns an explicit partial investigation report when:
   - sufficiency is not met,
   - materialization fails,
   - consensus is not ready.

2. The executor no longer silently falls through from failed evidence convergence into unrelated generic web sources.

3. Delegated final synthesis filters out source-only participant answers.

4. If the output node is missing but an investigation report exists, the primary client surfaces that report instead of hiding intermediate data or using a wrong source.

5. Packaging boundary keeps source secret modules such as `ai_core/secrets/secret_store.py` and excludes only runtime secret values.
