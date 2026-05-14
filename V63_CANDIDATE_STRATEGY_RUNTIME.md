# v63 Verified Candidate Strategy Selection Runtime

## Fixes

- Trace writing now uses safe JSON serialization to prevent circular-reference crashes.
- Execution provenance writing now uses safe JSON serialization.
- Sandbox verification treats `result.error` as a failed sandbox result even if the process exits with code 0.
- Failed sandbox artifacts are not safe to register.
- Tool output schema validation now accepts schema-compatible `data` payloads instead of requiring generated tools to duplicate fields at the top level.
- API and Web candidates are merged into one candidate pool.
- Each candidate receives light verification and a runtime strategy score.
- Candidate tool type is inferred generically as `json_api`, `html_extract`, `browser_extract`, or `skip`.
- Highest-scoring candidates are tried first; execution falls back to the next candidate on failure.
- Fallback attempts stored in final results are compact summaries, avoiding recursive provenance nesting.
- Capability resolution now distinguishes registered tools/modules, external information lookup, and missing runtime capability code generation.

## Runtime Principle

Runtime does not assume API is always better than Web. It verifies both and selects the candidate that is accessible, stable, complete, and safe to execute.
