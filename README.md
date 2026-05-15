# CDAC NestHub v70.7

## Capability-aware code generation model routing

This version stays on the v70 runtime line. It does **not** switch to v2.1.

## Main change

Runtime code-generation tasks now use code-specialized models first instead of the default vision/reasoning model.

Code artifact tasks include:

- runtime tool generation
- adapter generation
- module generation
- schema repair
- generated tool repair

## Default routing

```yaml
routes:
  code_generation:
    - ollama_coder_qwen25
    - ollama_coder_deepseek
    - vllm_coder
    - lmstudio_coder
    - ollama
    - openai
```

## Added local code model providers

### ollama_coder_qwen25

Primary model:

```text
qwen2.5-coder:7b
```

Fallback models:

```text
qwen2.5-coder:14b
qwen2.5-coder:3b
qwen3:8b
qwen3:4b
```

Capabilities:

```text
code_generation
python_generation
adapter_generation
schema_repair
structured_output
json_generation
tool_generation
```

### ollama_coder_deepseek

Primary model:

```text
deepseek-coder-v2:16b
```

Fallback models:

```text
deepseek-coder-v2:lite
qwen2.5-coder:7b
qwen3:8b
```

## Model selection behavior

The core does not hardcode vendor-specific logic. It only passes generic capability requirements:

```text
code_generation
python_generation
adapter_generation
schema_repair
structured_output
json_generation
```

`ModelCapabilityMatcher` then ranks runtime provider candidates by declared tags, capabilities, quality hints, and priority.

## Important runtime behavior

- `qwen3-vl:8b-thinking` remains available for vision / screenshot / UI-understanding tasks.
- It is no longer preferred for pure code generation.
- OpenAI remains an external fallback only.
- Existing `runtime/configs/models/providers.yaml` is upgraded by bootstrap instead of being skipped.

## Packaging rules

The ZIP package includes source/config/schema/templates only.

Excluded runtime artifacts:

```text
runtime/generated/
runtime/cache/
runtime/traces/
runtime/tmp/
runtime/downloads/
__pycache__/
*.pyc
```
