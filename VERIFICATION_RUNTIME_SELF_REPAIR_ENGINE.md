# Runtime Self-Repair Engine Verification

This package adds a generic, domain-neutral self-repair layer under:

`ai_core/runtime/self_repair/`

It is additive and assistive by default. Existing runtime chains do not change
unless callers explicitly invoke `RuntimeSelfRepairEngine`.

## Covered repair levels

1. Deterministic repair
   - schema type coercion
   - parameter alias binding from runtime-declared aliases
   - unresolved variable resolution from runtime state
2. Runtime knowledge repair
   - checkpoint material recovery hook
3. Web evidence repair
   - optional advisor, disabled by default by policy
4. Human escalation
   - used when no safe deterministic repair is available

## Guardrail

`FinalAnswerGuard` blocks unsupported success claims when verified material is
missing, especially for external actions.

## Verification command

```bash
python tools/verify_runtime_self_repair.py
python -m compileall ai_core apps auxiliary_brain
```

Expected output:

```text
Runtime Self-Repair Engine verification passed
```
