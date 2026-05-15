# v69/v70 Runtime Model Governance

This release merges the v69 runtime context/token governance layer with the v70 universal model adapter layer.

## Main changes

1. Added domain-neutral runtime context reduction before LLM calls.
2. Added provider-neutral prompt budget management.
3. Added approximate token estimation without provider-specific tokenizers.
4. Added generic model response cache under `runtime/cache/model_responses`.
5. Added provider-neutral token usage logging under `runtime/metrics/token_usage.jsonl`.
6. Replaced provider-specific model handlers with `UniversalModelProviderHandler`.
7. Runtime provider behavior is now configured by `protocol`, `base_url`, `endpoint`, `auth_type`, and model settings.
8. OpenAI-compatible, vLLM, LM Studio, and Ollama-style providers are handled through runtime configuration instead of dedicated core adapter files.
9. Added request timeout, prompt-size telemetry, cache-hit events, and token/latency records.
10. Kept ai_core domain-neutral: no weather/flight/booking business logic and no per-model adapter implementation.

## Runtime output paths

Generated runtime artifacts are excluded from source packages:

- `runtime/generated/`
- `runtime/traces/`
- `runtime/downloads/`
- `runtime/cache/`
- `runtime/metrics/`
- temporary files and Python caches

## Provider configuration concept

Providers should be configured like this:

```yaml
providers:
  openai:
    enabled: true
    type: universal_model
    protocol: openai_compatible
    base_url: https://api.openai.com
    endpoint: /v1/chat/completions
    auth_type: bearer_env
    auth_env: OPENAI_API_KEY
    model: gpt-4o-mini
    timeout_seconds: 60
    max_prompt_tokens: 12000
    cache_enabled: true

  vllm:
    enabled: false
    type: universal_model
    protocol: openai_compatible
    base_url: http://127.0.0.1:8001
    endpoint: /v1/chat/completions
    auth_type: none
    model: Qwen/Qwen2.5-7B-Instruct

  ollama:
    enabled: true
    type: universal_model
    protocol: ollama_chat
    base_url: http://127.0.0.1:11434
    model: qwen3:4b
```

## Design rule

`ai_core` defines contracts, validation, routing lifecycle, sandbox boundaries, and generic execution mechanisms. Runtime-generated or runtime-configured files define provider/tool-specific behavior.
