# Local Model Switch and vLLM-first Runtime Policy

Version: 2.9.4

## Goal

The runtime must support two operating modes without changing business logic:

1. **Hybrid mode**: use local models first where suitable, then API models as fallback.
2. **API-only mode**: completely skip local model providers and use API providers only.

Local runtime priority is:

```text
vLLM -> Ollama -> API fallback
```

For code generation:

```text
vLLM coder -> Ollama coder -> API fallback
```

## Switch

The switch is defined in `model_stage_policy.seed.json`:

```json
"global_policy": {
  "runtime_switch": {
    "local_models_enabled": true
  },
  "local_model_policy": {
    "enabled": true,
    "default_provider_order": ["vllm", "ollama"],
    "code_provider_order": ["vllm_coder", "ollama_coder_qwen25", "ollama_coder_deepseek"],
    "api_provider_order": ["openai", "claude"],
    "api_only_when_disabled": true
  }
}
```

Runtime override is also supported:

```bash
AI_CORE_LOCAL_MODELS_ENABLED=false
```

Accepted off values:

```text
0, false, no, off, api_only, api-only
```

## Behavior

When local models are enabled:

```text
stage model candidate -> vLLM virtual provider -> Ollama virtual provider -> API fallback
```

When local models are disabled:

```text
stage model candidate -> API provider only
```

Legacy adapter routes such as `["ollama", "openai"]` are also filtered by `ProviderRouter`, so API-only mode remains enforced even if an old adapter still contains local providers.

## Provider bootstrap defaults

`core_bootstrap.py` now initializes:

```text
default_route = ["vllm", "ollama", "openai"]
```

and enables:

```text
vllm = enabled
vllm_coder = enabled
```

If vLLM is not running, the connection fails and the route continues to Ollama, then API fallback.

## Required vLLM server examples

General model:

```bash
python -m vllm.entrypoints.openai.api_server \
  --host 127.0.0.1 \
  --port 8001 \
  --model Qwen/Qwen3-8B
```

Coder model:

```bash
python -m vllm.entrypoints.openai.api_server \
  --host 127.0.0.1 \
  --port 8002 \
  --model Qwen/Qwen2.5-Coder-7B-Instruct
```

The runtime calls vLLM through the OpenAI-compatible `/v1/chat/completions` API.

## Files changed

- `ai_core/runtime/modeling/model_stage_policy.py`
- `ai_core/llm/provider_router.py`
- `ai_core/runtime/bootstrap/core_bootstrap.py`
- `ai_core/runtime/bootstrap/provider_discovery.py`
- `configs/model_stage_policy.seed.json`
- `configs/provider_runtime_templates.seed.json`
- `runtime/generated/system_topology/model_stage_policy.json`
