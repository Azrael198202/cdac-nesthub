# v2.9.32 Runtime Dependency Self-Healing

This version adds a generic runtime dependency repair layer. When a runtime capability needs a Python package, CLI command, or browser runtime, the execution layer can check, install, verify, and continue under a configurable permission policy. The default local-development policy is administrator-level and allows shell, Python, package install, and system dependency repair.

Key additions:
- `ai_core/runtime/environment/permission_policy.py`
- `ai_core/runtime/environment/runtime_command_executor.py`
- `ai_core/runtime/environment/runtime_dependency_manager.py`
- `ai_core/runtime/generated_execution/runtime_command_service.py`
- Playwright browser auto-repair before browser/network observation
- Dependency recovery traces under `runtime/traces/dependency_recovery/`
- Source packaging manifest that preserves source modules such as `ai_core/secrets/*` while excluding runtime secret values.

# cdac-nesthub v2.9.10

# AI Runtime OS v2.9.0 Runtime Boundary Stabilization

This source package reorganizes the runtime around a clear boundary:

- `auxiliary_brain` is the conversational control layer. It manages user dialogue, participants, tasks, context, missing-information collection, feedback, and rerun requests.
- `ai_core` is the primary execution brain. It performs input parsing, intent recognition, workflow planning, capability/model routing, tool/MCP/CLI execution, evidence verification, and final answer synthesis.

## Key Runtime Guarantees

1. The auxiliary layer does not execute tools, web retrieval, shell commands, code generation, or final reasoning.
2. The primary runtime does not manage participant/task communities directly.
3. The two layers communicate through a canonical request envelope.
4. Runtime-native execution is limited to runtime-state observations only.
5. External/volatile information must route to structured providers, web retrieval, generated capabilities, or MCP.
6. Intermediate node JSON is not exposed as the user-facing final answer.
7. Natural-language feedback can trigger model escalation and re-optimization.
8. Runtime model/capability topology is generated or refreshed at startup under `runtime/generated/system_topology`.


## v2.9.1 stage-bound model policy

This version adds a generic model-stage policy layer:

- `runtime/generated/system_topology/model_stage_policy.json` binds each cognitive stage to default, fallback, upper-substitute, and lower-substitute models.
- `configs/model_stage_policy.seed.json` is the source fallback used to recreate the runtime policy.
- `schema/model_stage_policy.schema.json` validates the policy shape.
- `ModelStagePolicy` expands stage policy into provider/model-specific virtual routes at runtime.
- JSON schema validation failure now triggers one model escalation attempt before auto-repair.
- Global paid/free behavior is controlled by `global_policy.cost_policy.allow_paid_models`.
- Local models are not downloaded during bootstrap; Ollama pulls them on demand only when selected.

The policy remains domain-neutral: model selection uses stage ids, capabilities, tier, cost class, schema status, and runtime signals, not business keywords.

## Runtime-generated model governance

At startup, `/api/runtime/bootstrap` performs:

- provider discovery from `runtime/configs/models/providers.yaml`
- feature inventory loading from `configs/runtime_feature_inventory.json`
- strong-model topology generation when available
- deterministic seed fallback when no strong model/key is available
- output of runtime-generated artifacts under:

```text
runtime/generated/system_topology/
├── runtime_governance_graph.json
├── model_stage_policy.json
├── model_inventory.json
├── model_requirements.json
├── missing_model_recommendations.json
└── feature_inventory_snapshot.json
```

These files are intentionally runtime-generated and are not packaged as source.

## Clean source policy

The package excludes:

```text
__pycache__/
*.pyc
tests/
scripts/
runtime/generated/*
runtime/traces/*
runtime/deliveries/*
runtime/checkpoints/*
```

Business/domain-specific routing terms must be generated into runtime contracts, not hardcoded into `ai_core` source.

## v2.9.2 Runtime Model Governance Policy

This package expands the model stage policy from a coarse routing list into a reusable runtime model governance layer. It includes a richer model catalog, multimodal capability taxonomy, stage-level validation/escalation/downgrade rules, paid/free controls, privacy controls, and generic support for audio, image, video, code, file, document, slide, spreadsheet, PDF, diagram, plan, report, evidence, and final synthesis stages.

See `docs/MODEL_STAGE_POLICY_DESIGN.md`.

## v2.9.29 Browser materialized structured evidence

- Added a domain-neutral embedded structure extractor for script JSON and data-* payloads.
- Added a domain-neutral DOM relation extractor for rendered tables and relation-like cells.
- Deep web research now materializes browser observations in this order: network JSON, embedded machine-readable structures, rendered DOM relations, then generic sequence fallback.
- Structured browser evidence prevents free-text numeric extraction from polluting results with page metadata/navigation values.
- Packaging preserves source/runtime code and excludes generated runtime artifacts, traces, checkpoints, caches, secrets, __pycache__, and .pyc files.


## v2.9.30
- Tightened generic evidence sufficiency so runtime lists/dates are preserved.
- Prevented transport/envelope text from dominating semantic scoring.
- Added stricter measurement-bearing material gates before final synthesis.
- Preferred structured/target-aligned facts over raw page headings or metadata.

## v2.9.31 DeepSearch white-box trace

Adds a generic, domain-neutral white-box trace for layered browser/web evidence processing.
When enabled, the runtime writes compact JSONL events under `runtime/traces/deepsearch_whitebox/<run_id>/` for:

1. Playwright/browser observation start and result
2. Network/XHR/JSON response extraction
3. Embedded machine-readable payload extraction
4. Script JSON extraction
5. DOM relation/table extraction
6. HTTP fallback extraction
7. Temporal/numeric sequence fallback
8. Evidence reduction and final material selection

The trace records candidate counts, selected URLs, fact counts, material previews, quality gate values, and skip/failure reasons without adding domain-specific logic.

## v2.9.33 - Generic multi-source evidence consensus

- DeepSearch no longer stops on a single source merely because one page has numeric material.
- Multiple independent sources are materialized first, then normalized into generic observations.
- A domain-neutral consensus layer evaluates source diversity, runtime-target alignment, numeric agreement, field coverage, structure quality, and outliers.
- Final LLM material is generated only from compact consensus material, not raw pages or single-source fallback text.
- Added white-box trace stages for consensus after browser materialization, fallback extraction, and final fusion.
- No business/domain keyword rules were added.
