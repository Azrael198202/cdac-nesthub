# v62 Multi-Candidate Execution Fallback Runtime

## Goal

v62 prevents workflow termination after a single runtime API or web candidate fails.

The runtime now classifies failed execution results and tries alternate candidates before returning a final failure.

## New Components

- `ai_core.execution.result_classifier.ResultClassifier`
  - Classifies generic failures such as timeout, 401/403, invalid JSON, HTML response, unsupported content type, and other retryable external failures.

- `ai_core.execution.candidate_extractor.CandidateExtractor`
  - Extracts retry candidates from runtime discovery metadata, candidate lists, selected candidates, web evidence, and documentation evidence.

- `ToolCallExecutor._try_multi_candidate_fallback_execution`
  - Generates a candidate-specific runtime artifact.
  - Runs sandbox verification.
  - Executes the registered fallback artifact.
  - Stops only when one candidate succeeds or all candidates fail.

## Execution Rule

```text
candidate_1 -> failed -> classify -> continue
candidate_2 -> failed -> classify -> continue
candidate_3 -> success -> return success
```

Only after every available candidate fails does the runtime return final failure.

## Important Guarantees

- No domain-specific logic was added to `ai_core`.
- Candidate selection uses runtime discovery evidence only.
- Every attempt is recorded as an execution event.
- Tool outputs with `error` are never recorded as success provenance.
- Generated tools must return JSON-serializable dictionaries.

