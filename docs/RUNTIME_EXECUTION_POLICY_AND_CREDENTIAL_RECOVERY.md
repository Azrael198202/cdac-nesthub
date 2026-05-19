# Runtime Execution Policy and Credential Recovery

This version unifies runtime provider execution switches into one canonical policy object.

## Single source of truth

The authoritative field is:

```json
{
  "global_policy": {
    "runtime_execution_policy": {
      "default_mode": "api_only",
      "local_enabled": false,
      "api_only_when_local_disabled": true,
      "api_provider_order": ["openai", "claude"],
      "local_provider_order": ["vllm", "ollama"],
      "local_code_provider_order": ["vllm_coder", "ollama_coder_qwen25", "ollama_coder_deepseek"],
      "credential_recovery_enabled": true
    }
  }
}
```

Legacy keys such as `runtime_switch.local_models_enabled` and `local_model_policy.enabled` are only backward-compatible mirrors. New resolver code reads `RuntimeExecutionPolicy`.

## API-only behavior

When `local_enabled=false`, all local providers are removed from candidate routes before execution. This includes vLLM, Ollama, LM Studio, and local HuggingFace inference providers.

The environment variable `AI_CORE_LOCAL_MODELS_ENABLED` can override the JSON policy. Values such as `false`, `0`, `off`, `api_only`, or `api-only` force API-only mode.

## Credential recovery

If the selected API provider requires a key and the key is missing, the runtime creates a `secret_input` pending action. Agent Studio displays a password field. After submission, the value is saved through `SecretStore` and the runtime resumes from the same checkpoint.

Secrets are stored in `runtime/configs/secrets/secrets.json` for local development. Production deployments should replace this with a managed secret store.
