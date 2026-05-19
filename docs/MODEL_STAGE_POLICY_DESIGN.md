# Runtime Model Governance Policy 2.9.2

This document describes the stable model-control layer introduced for the runtime.
It is intentionally domain-neutral: the policy uses stage, capability, modality,
validation, cost, privacy, and provider concepts only. It must not contain
business/task-specific keywords.

## 1. Core idea

The runtime must not let a small model freely decide intent, capability routing,
execution mode, final synthesis, or model routing. Every judgment point is a
controlled runtime stage. Each stage declares:

- default model or deterministic component
- fallback models
- upper substitutes for quality escalation
- lower substitutes for free/local mode
- required capabilities
- required input/output modalities
- validation rules
- raw evidence rules
- cost behavior
- privacy behavior
- execution mode

The LLM may propose candidates, but the runtime resolver chooses through policy,
schema validation, benchmarks, and operator preferences.

## 2. File layout

```text
configs/model_stage_policy.seed.json
runtime/generated/system_topology/model_stage_policy.json
schema/model_stage_policy.schema.json
ai_core/runtime/modeling/model_stage_policy.py
```

`configs/model_stage_policy.seed.json` is the stable default policy.
`runtime/generated/system_topology/model_stage_policy.json` is the runtime copy
that can be adjusted by governance workflows. Seed should not be overwritten by
runtime learning.

## 3. Catalog model

`model_catalog` is no longer only a list of model names. Each entry describes:

```json
{
  "provider_template": "openai",
  "provider_model": "gpt-4.1",
  "family": "openai",
  "vendor": "openai",
  "tier": "external_strong",
  "cost_class": "paid",
  "deployment": "external_api",
  "install_strategy": "key_required",
  "status": "approved",
  "modalities": {"input": ["text", "image"], "output": ["text", "structured_data"]},
  "capabilities": ["reasoning", "workflow_planning", "final_synthesis"],
  "context_window_hint": 1000000,
  "priority_bias": 70
}
```

This allows the runtime to support local models, paid APIs, deterministic runtime
components, STT, TTS, image generation, video generation, file generation,
code generation, and future models using the same structure.

## 4. Stage model

Each runtime stage looks like this:

```json
{
  "default": "qwen3:32b",
  "fallback": ["gpt-4.1"],
  "upper_substitutes": ["gpt-5.x", "claude-sonnet"],
  "lower_substitutes": ["qwen3:14b"],
  "required_capabilities": ["workflow_planning", "json_generation"],
  "required_modalities": {"input": ["text"], "output": ["structured_data"]},
  "execution_mode": "llm_or_policy",
  "validation": {"schema_required": true, "escalate_on_failure": true, "max_validation_attempts": 2},
  "raw_evidence_policy": {"raw_evidence_allowed": false, "reduced_material_required": true},
  "privacy_policy": {"allow_external": "inherit_model", "redaction_required": true},
  "selection": {"require_capability_match": true, "require_modality_match": true, "allow_candidate_status": true, "prefer_benchmark_score": true}
}
```

## 5. Supported stage families

The seed policy includes these generic stage families:

- language and intent: language detection, input parsing, simple/complex intent,
  translation
- governance: capability classification, execution mode decision, model routing,
  workflow planning, tool selection
- code/tool/schema: tool generation, code generation, code review, schema design,
  schema repair
- retrieval/evidence: embedding generation, query rewrite, reranking, evidence
  extraction, evidence compression, fact verification
- synthesis/feedback/memory: final synthesis, feedback understanding, memory
  update
- artifacts: document, report, plan, slides, spreadsheet, PDF, file transform,
  diagram
- audio: speech-to-text, text-to-speech, audio generation
- image: image understanding, image generation, image editing
- video: video understanding, video generation

## 6. Stable operating rule

Do not fix stability by adding ad-hoc logic to each bug. Fix stability by adding
or adjusting one of these generic controls:

1. stage definition
2. model catalog metadata
3. capability taxonomy
4. schema validation
5. escalation/fallback rule
6. benchmark score
7. cost/privacy policy
8. deterministic registry/parser/validator rule

## 7. Runtime learning rule

Runtime learning may write scores and candidate status to generated runtime
policy files, but it should not directly overwrite the seed policy. New model
recommendations from a strong model enter as `candidate` or `alias_candidate` and
must pass benchmark and schema-stability checks before becoming `approved`.
