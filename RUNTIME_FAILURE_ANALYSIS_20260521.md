# Runtime failure analysis and fixes (2026-05-21)

## Observed failures

1. `AttributeError: 'PrimaryBrainDelegationClient' object has no attribute '_extract_investigation_report_answer'`
   - Cause: `_extract_final_answer()` calls `_extract_investigation_report_answer(results)`, but the method was not implemented.
   - Impact: when the workflow timed out or completed without `results.output.final_answer`, final answer extraction crashed and the Studio API returned an HTTP 500 text response.
   - Browser symptom: `SyntaxError: Unexpected token 'I', "Internal S"... is not valid JSON`, because the frontend tried to parse the server's `Internal Server Error` text as JSON.

2. Primary runtime timeout at `input_parsing`
   - Runtime checkpoint `b384f2157451.json` shows `status=failed`, `timeout_seconds=210`, `current_node_index=0`.
   - Trace shows the run started `input_parsing`, then no node result was produced before the outer primary-runtime timeout finalized the run.
   - The selected local model was `qwen3:8b`. The generated provider route was `vllm -> ollama`, with local provider timeouts that can exceed the outer runtime timeout when tried sequentially.
   - Impact: outer timeout may cancel the whole workflow before provider fallback and diagnostic events complete.

3. Non-JSON provider/server responses were not normalized
   - Provider handlers called `response.json()` and `json.loads()` directly.
   - Impact: HTML/text bodies such as `Internal Server Error`, proxy errors, or model server errors surfaced as opaque JSON parsing failures instead of structured provider failures that the router can skip/fallback from.

## Code fixes included

1. Added `PrimaryBrainDelegationClient._extract_investigation_report_answer()` and `_coerce_user_text()`.
   - Generic, domain-free final answer extraction from intermediate node results.
   - Prevents final-answer extraction from crashing when output node is absent.

2. Increased primary delegated runtime outer timeout formula.
   - Changed from `operation_timeout + 30` with minimum `30` to `operation_timeout + 120` with minimum `300`.
   - This gives local provider fallback chains enough time to fail/return cleanly instead of being killed at the workflow boundary.

3. Hardened provider JSON parsing.
   - `parse_json_content()` now extracts the first balanced JSON object from noisy model text and raises a clear error when content is not JSON.
   - Added `response_json_or_error()` to convert non-JSON HTTP bodies into structured errors with provider/endpoint/status/preview.
   - Updated Ollama and universal model handlers to use this helper.

4. Hardened Studio execution response.
   - `AgentStudioService.execute_task()` now catches runtime exceptions and returns a structured JSON error payload.
   - This prevents the browser from receiving plain `Internal Server Error` and then failing with `Unexpected token 'I'`.

## Remaining operational requirement

The code is now more fault-tolerant, but successful execution still requires at least one selected model provider to be truly usable:

- If using vLLM, `http://127.0.0.1:8001/v1/chat/completions` must respond with OpenAI-compatible JSON.
- If using Ollama, `qwen3:8b` must be loaded fast enough for the configured timeout, or use a smaller model for early stages.
- For strict local-only mode, keep early-stage models small/stable and reserve larger models for code generation or final synthesis.

Recommended runtime environment variables while testing local models:

```bash
set AI_CORE_OPERATION_TIMEOUT_SECONDS=420
set AI_CORE_MAX_PROVIDER_ATTEMPTS=2
set AI_CORE_MAX_PROMPT_TOKENS=3500
```

For Windows PowerShell:

```powershell
$env:AI_CORE_OPERATION_TIMEOUT_SECONDS="420"
$env:AI_CORE_MAX_PROVIDER_ATTEMPTS="2"
$env:AI_CORE_MAX_PROMPT_TOKENS="3500"
```

