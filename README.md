# CDAC NestHub v70.6

## Runtime Execute Stabilization

This version is based on v70.5 and keeps the v70 architecture line.

## Main Fixes

1. `execute` no longer waits silently after enough no-key web evidence has already been collected.
2. Before runtime tool generation, the executor now tries `direct_evidence_execution`.
3. Large `api_discovery`, `documentation_evidence`, and `endpoint_verification` JSON are no longer emitted as full UI log payloads.
4. `RUNTIME_TOOL_GENERATION_STARTED` now emits a compact generation request only.
5. LLM code generation receives compact evidence, not raw discovery JSON.
6. If evidence covers runtime parameters, execution can finish through `evidence_direct_answer` without generating a tool.
7. The execute stage keeps token usage lower and avoids unnecessary OpenAI/Ollama calls.
8. `qwen3-vl:8b-thinking` remains the preferred local model from v70.5 configuration.

## Runtime Policy

Execution priority:

```text
registered tool/module
↓
no-key evidence direct answer
↓
deterministic web_extract
↓
compact LLM-generated tool
↓
optional credential interaction
```

## Packaging Rules

Runtime generated artifacts, traces, cache, downloads, temporary files, and old version Markdown files are excluded from the ZIP package.
