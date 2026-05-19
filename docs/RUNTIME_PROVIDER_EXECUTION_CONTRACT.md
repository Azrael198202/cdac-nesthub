# Runtime Provider Execution Contract

This version separates model selection from provider execution methods.

A runtime provider artifact defines:

1. `provider_id`
2. `provider_type`
3. `prepare` method: binary install, service start, model download, secret check, or module validation
4. `invoke.method`: `ollama_chat`, `ollama_generate`, `chat_completions`, `http_json`, `command`, or `python_function`
5. `input_schema`
6. `output_schema`
7. capabilities and modalities

The runtime can therefore generate a provider/tool artifact, validate it, register it, and invoke it through a generic contract.

Provider families covered by the seed policy:

- Ollama local service models
- OpenAI-compatible API models
- HuggingFace snapshot models bound to a local command or Python runtime
- Generic HTTP JSON APIs
- Local command tools
- Runtime Python function tools

The contract intentionally avoids business-domain keywords. Capabilities such as STT, TTS, image generation, video generation, file generation, code generation, and document generation are represented as generic capability labels and are bound to provider execution methods through `configs/provider_runtime_templates.seed.json`.
