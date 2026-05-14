# v67 Evidence Quality Runtime

## Goal

v67 prevents a runtime tool from returning `status=success` when the extracted answer material is only documentation, sample data, demo JSON, or otherwise unrelated to the current runtime parameters.

The implementation remains domain-neutral. It does not hard-code any business terms, locations, dates, providers, or APIs. It validates output against the parameters already parsed at runtime.

## Changes

1. Added `EvidenceQualityValidator`.
2. Added dynamic required evidence term generation from `payload.parameters.known` / `payload.known`.
3. Added date alias generation for ISO dates.
4. Added generic sample/demo detection.
5. Converted low-quality success results into structured retryable errors.
6. Updated generic web extraction tool generation to fail sandbox verification when extracted material does not cover runtime parameters.
7. Added no-credential-first scoring and stronger penalty for credential-protected candidates.
8. Added credential-protected candidate handling:
   - skip protected candidates by default while no-credential candidates remain
   - if only protected candidates exist, return a human interaction choice
9. Added candidate quality gate before accepting fallback success.

## Runtime Policy

Priority order:

1. Verified source that does not require credentials and returns usable data.
2. Verified HTML/text source that does not require credentials and contains runtime parameter evidence.
3. Credential-protected source only after user choice.
4. Unverified or sample/demo-only sources are rejected.

## Generic Evidence Rule

For each execution result:

```text
answer_material must cover critical runtime parameters from payload.known.
```

Examples of runtime parameter aliases are generated dynamically. For dates, ISO values such as `YYYY-MM-DD` produce aliases like `YYYY/MM/DD`, `Month D`, and `D Month`.

## Human Interaction for Credentials

If a candidate requires credentials, the runtime does not fail immediately. It can return a structured interaction asking the user to either:

1. provide the credential and retry the protected source, or
2. skip protected sources and continue/finish with no-key methods.
