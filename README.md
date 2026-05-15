# CDAC NestHub v70.19

## Runtime Final Answer Synthesis

This version changes the output contract:

- Execution steps produce **result material** only.
- Raw source payloads are sanitized before presentation.
- Raw markup, raw JSON, traces, logs, and transport payloads are not returned directly as the final answer.
- A final synthesis stage creates the user-facing response from sanitized material.
- If model synthesis is unavailable, a deterministic rule-based summary is used as fallback.

## Main Changes

1. Added `ResultMaterialBuilder`.
2. Added `ResultSanitizer`.
3. Added `FinalAnswerSynthesizer`.
4. Updated `OutputExecutor` to call final synthesis after execution.
5. Preserved `trust_summary`, `provenance`, and `result_material` as metadata, separate from the main answer.
6. Kept runtime evidence rules domain-neutral: no business/domain keyword hardcoding in generic output synthesis.

## Output Principle

```text
runtime execution
  -> result material
  -> sanitizer
  -> final answer synthesizer
  -> user-facing answer
```

## Packaging

Excluded:

```text
runtime/generated/
runtime/cache/
runtime/traces/
runtime/tmp/
__pycache__/
*.pyc
```
