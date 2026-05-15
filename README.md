# CDAC NestHub v70.11

## Runtime Knowledge Evidence Type Filtering

This version fixes a critical runtime priority issue where local runtime memories such as workflow success patterns or prompt optimization records could be incorrectly treated as final answer evidence.

### Main Changes

1. Added final-answer eligibility classification in `KnowledgeService`.
2. `success_pattern`, `prompt_optimization`, `workflow_template`, and internal workflow memories are now hint-only.
3. Local knowledge may only finish execution when it is classified as final answer evidence.
4. Eligible final answer memory types include:
   - `factual_observation`
   - `verified_web_evidence`
   - `tool_execution_result`
   - `user_provided_document_fact`
   - `answer_result`
   - `verified_result`
5. Matching workflow-planning memories can still be used as prompt/runtime hints, but they no longer stop execution.
6. If local knowledge is only a hint, execution continues to web/API/tool execution.
7. Prevents `prompt_optimization_memory.jsonl` content from being shown as the final answer.

### Validation

- `compileall`: OK
- `success_pattern` classification: hint-only
- `verified_web_evidence` classification: final-answer evidence

### Packaging Rule

Runtime generated artifacts, traces, cache, metrics, and temporary files are excluded from this package.
