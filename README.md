# CDAC NestHub v70.9

## Runtime Priority Chain + Reusable Codegen Fix

This version stays on the v70 code line and does not switch to v2.1.

## Main fixes

1. Fixed module registry selection so executable modules are preferred over stale blueprint records.
2. Added automatic disabling of failed registered modules so a bad runtime-generated module does not block execution forever.
3. Added local runtime knowledge / RAG-first execution path before web/API/codegen.
4. Added web/evidence-first path before code generation when endpoint verification recommends web extraction.
5. Improved direct evidence answer with aggregate evidence coverage across multiple candidates.
6. Strengthened code-generation prompts so generated Python must be reusable and must not hardcode user-specific location/date/query values.
7. Kept code-specialized model routing from v70.7/v70.8.
8. Kept local model selector UI from v70.8.

## Execution priority

```text
1. Local model / local knowledge / RAG-style runtime memory
2. Web search / web extraction / direct evidence answer
3. Runtime-generated tool or module code generation
```

## Why this version was needed

The previous generated weather module was registered but not reusable:

```text
- hardcoded URL path
- hardcoded page structure
- attempted to parse HTML as JSON
- could not execute reliably
```

v70.9 prevents this from becoming a permanent blocker by disabling failed modules and continuing through the priority chain.

## Packaging rule

Runtime-generated files, traces, cache, metrics, and transient runtime directories are excluded from release ZIPs.
