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
