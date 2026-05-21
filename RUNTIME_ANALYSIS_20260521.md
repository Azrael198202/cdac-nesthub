# Runtime failure analysis and patch summary

## Observed failure

The latest run completed Weather Agent but failed to produce a verified answer. Time Agent failed at `input_parsing` with a local LLM timeout.

## Root causes

1. The participant prompt was still not reliably treated as a compact JSON envelope when it had an instruction prefix. Early LLM stages could receive more text than necessary.
2. Weather Agent's execution selected/generated a generic runtime observation tool, but the tool input builder passed planner parameters as `{known, optional}` instead of a flattened `parameters` object. The generated tool schema required fields at `$.parameters.*`, causing schema validation failure.
3. Time Agent started after a long Weather execution. Its `input_parsing` then hit the Ollama stage timeout. Without saved prompt/output traces it was hard to see whether the prompt was too long, the provider was overloaded, or the schema/prompt caused generation drift.
4. Participants are independent by default, but later participants need access to compact prior participant outputs when their own objective can benefit from them.

## Patch

- Preserved LLM-based `input_parsing`.
- Improved JSON envelope extraction from mixed instruction + JSON messages.
- Added runtime prompt/output/error tracing under `runtime/traces/llm/<run_id>/`.
- Added provider request/response/error tracing with provider/model/options/timeout metadata.
- Added compact peer result context for later participants.
- Fixed generic tool input mapping by flattening `parameters.known` and `parameters.optional` into schema-friendly `parameters` while preserving `raw_parameters`.
- Added generic runtime timestamp defaults for generated runtime observation tools.
- Reduced participant wrapper prompt length.

## Verification in sandbox

- `python -m compileall -q ai_core auxiliary_brain tests` passed.
- `PYTHONPATH=. python tests/smoke_fast_boot.py` passed.
- `PYTHONPATH=. python tests/smoke_runtime_no_provider.py` passed.
- JSON extraction smoke check passed.

## Runtime files intentionally excluded from package

- `runtime/generated/results/*.json`
- `runtime/deliveries/*.json`
- `runtime/traces/*`
- runtime cache/checkpoint/download transient files
- `__pycache__`
- `.pytest_cache`
