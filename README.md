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
