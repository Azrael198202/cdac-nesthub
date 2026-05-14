# v66 Web Extraction Runtime Reliability Update

## Goal

v66 improves runtime execution when the selected external candidate is an HTML page rather than a verified JSON API. The core remains domain-neutral: it does not contain business-specific terminology, selectors, providers, or API names.

## Key changes

1. HTML candidates can produce a deterministic generic web extraction artifact when LLM-generated adapter code fails sandbox validation.
2. The fallback artifact always exposes `def run(payload: dict) -> dict`.
3. Sandbox verification can pass using either live page fetch or verified page evidence collected earlier in the same runtime trace.
4. The generated output uses a common result contract:
   - `status`
   - `data`
   - `source`
   - `requires_human_confirmation`
5. The extraction uses only already-structured runtime parameters from `payload.known` or `payload.parameters.known`.
6. Candidate fallback still tries candidates in score order and only stops when one candidate passes verification and execution.

## Runtime flow

```text
candidate pool
  ↓
light verification
  ↓
LLM adapter generation
  ↓ if sandbox fails
static generic web extraction artifact
  ↓
sandbox verification with real payload
  ↓
register enabled tool
  ↓
execute tool
  ↓
final answer generation from extracted evidence
```

## Design boundary

The generic fallback does not know the task domain. It only performs:

- URL fetch with timeout
- HTML stripping
- keyword/snippet selection using runtime payload values
- JSON-safe result formatting

Business interpretation and final natural-language answer generation remain outside the core execution primitive.
