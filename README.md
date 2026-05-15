# CDAC NestHub v70.22

## Focus

This version keeps the v70 runtime line and adds an evidence-continuation fix for cases where a generated or registered runtime component is rejected as unverified.

## Main changes

1. Added `ExecutionContinuationCoordinator`.
2. Generated or registered execution results rejected for missing evidence are no longer terminal.
3. Runtime now continues to the generic evidence path when discovery already contains usable source candidates.
4. Candidate extraction now preserves fetched document objects from external discovery.
5. Direct evidence extraction now reads nested fetched documents, page excerpts, DOM evidence, and attribute evidence instead of relying only on snippets.
6. Final synthesis remains the only user-facing answer layer; raw HTML, raw JSON, and traces are not returned as final answers.
7. The implementation remains domain-neutral. Generic runtime files do not hardcode task-specific terms.

## Intended flow

```text
candidate execution
↓
verification rejects synthetic/unverified output
↓
ExecutionContinuationCoordinator
↓
existing evidence candidates
↓
fetched page / DOM / structured evidence extraction
↓
result material
↓
final answer synthesis
```

## Packaging

Runtime artifacts are excluded:

```text
runtime/generated/
runtime/cache/
runtime/traces/
runtime/tmp/
runtime/downloads/
__pycache__/
*.pyc
```
