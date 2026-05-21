# Fix report 2026-05-21

## Confirmed root cause

The uploaded runtime trace shows both participants failed at `input_parsing` because no real local LLM provider was available:

```text
No real LLM provider is available...
stage_input_parsing_vllm_qwen3_8b: Local provider did not become ready after auto-start.
provider=stage_input_parsing_vllm_qwen3_8b, base_url=http://127.0.0.1:8001
```

The generated provider config routes `input_parsing` to vLLM first, but the source `requirements.txt` did not include `vllm`, and the local server was not already running at `127.0.0.1:8001`. The previous code tried to auto-start `python -m vllm...`, waited for readiness, and eventually failed.

A second logic bug then hid the real cause: the primary runtime emitted `RUN_FAILED`, but did not persist `state["status"] = "failed"` or a structured error result. `PrimaryBrainDelegationClient` therefore extracted a placeholder answer and `_extract_status()` returned `completed`. The delegation runtime then recorded failed participants as completed. Final synthesis omitted these placeholder answers and produced `completed_with_no_participant_result`.

## Code changes

1. `ai_core/llm/provider_handlers/universal_model_handler.py`
   - Added fast module precheck for local OpenAI-compatible auto-start commands using `python -m ...`.
   - If `vllm` is not installed, the runtime fails immediately with a clear provider diagnostic instead of waiting for the readiness timeout.
   - Detects immediately exited provider start commands.

2. `ai_core/runtime/modeling/model_runtime_preflight.py`
   - Added the same missing-module check to preflight.
   - Local-only mode no longer treats an unreachable auto-start provider as OK when its Python module is missing.

3. `ai_core/orchestration/workflow_runtime.py`
   - On capability or node execution failure, stores:
     - `state["status"] = "failed"`
     - `state["error"] = ...`
     - `state["results"][node_id] = {"status": "failed", "message": ...}`
   - On success, explicitly stores `state["status"] = "completed"`.

4. `ai_core/agent_delegation/primary_brain_client.py`
   - Added `_extract_investigation_report_answer()` to avoid the previous missing-method crash.
   - Failed participant runs now return the real failure message, not the placeholder.
   - Failed participants are not considered usable for final synthesis.
   - If no usable participant exists, synthesis status is `failed` and the final answer includes failure details.

5. `auxiliary_brain/delegation/delegation_runtime.py`
   - Delegation run status now becomes `failed` when final synthesis status is failed.
   - Failed participant status is preserved instead of being converted to success.

6. Added `requirements-vllm.txt`
   - vLLM is kept as an optional GPU/Linux dependency rather than forcing heavy GPU packages into the default app install.

7. Added `tests/smoke_runtime_no_provider.py`
   - Runs without vLLM/Ollama/OpenAI/GPU.
   - Verifies the runtime fails fast and returns structured diagnostics.

## Sandbox verification

Command executed in sandbox:

```bash
PYTHONPATH=. python tests/smoke_runtime_no_provider.py
```

Result:

```json
{
  "ok": true,
  "elapsed_seconds": 0.92,
  "status": "failed",
  "participant_status": "failed"
}
```

This proves the updated code runs in the sandbox and fails correctly when no model provider is installed, instead of timing out or returning a fake completed result.
