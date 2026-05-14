# v60 Endpoint Verification + Web Extraction Fallback

v60 adds a runtime verification layer between discovery and executable artifact generation.

## Key changes

1. Discovery candidates are verified by real HTTP checks.
2. JSON API support is accepted only when the endpoint returns parseable JSON.
3. HTML pages are explicitly marked as web extraction candidates.
4. Tool generation receives `runtime_endpoint_verification` and must not invent JSON API access.
5. Static sandbox failures now include concrete findings.
6. When a generated API tool fails verification, runtime automatically tries a generic web-extraction fallback.
7. Packaging excludes runtime-generated/transient state.

## Non-goals

No domain or provider-specific logic is added to `ai_core`.
