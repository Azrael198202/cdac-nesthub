# cdac-nesthub v15

This package keeps `ai_core` as a generic runtime brain and operating-system layer. Concrete capabilities are generated, combined, executed, verified, and registered at runtime-owned boundaries instead of being embedded as fixed core behavior.

## v15 design boundary

- `ai_core`: generic brain, runtime contracts, planning/execution/verification boundaries, self-repair, registry policy, and runtime OS services.
- `auxiliary_brain`: assistant layer for Studio, parameter completion, task/agent interaction, and user-facing orchestration support.
- Runtime-owned capability material:
  - `runtime/generated/`
  - `runtime/registry/`
  - `runtime/profiles/`
  - `runtime/secrets/`
- Static config boundary:
  - system policy
  - model routes
  - sandbox policy
  - approval defaults

## Runtime roles

v15 adds a neutral role contract in `ai_core.roles.runtime_role_contract`:

- Core system designer: designs the generic brain and auxiliary-brain boundary.
- Implementation engineer: implements the approved generic design without adding concrete task logic to core.
- Quality challenger: verifies stage boundaries, acquisition failure modes, registry boundary, and final synthesis safety.

These roles describe responsibilities only. They do not contain concrete capability logic or task-specific behavior.

## Core workflow stages

1. `input_parsing`: normalize text, file, and media inputs into text plus metadata while preserving raw input.
2. `intent_recognition`: classify the user's intended operation, required capability categories, missing information, and draft steps.
3. `requirement_completion`: pause for missing required parameters and resume after UI collection.
4. `context_awareness`: bind supplemental input to suspended work, build clean context, and keep independent agent outputs isolated.
5. `workflow_planning`: generate and lock the workflow, graph, execution method, tool/model/provider/source policy, and execution plan.
6. `pre_execution_validation`: check schema, parameters, tool availability, generation need, and approval requirement.
7. `execution`: execute only the locked plan and record trace, evidence, and provenance.
8. `result_verification`: verify real execution, step satisfaction, confidence, and planned fallback only.
9. `feedback_repair`: repair schema, parameters, state, variables, dependency, sandbox, or identity failures through the self-repair engine.
10. `final_synthesis`: collect step outputs and answer without re-executing, re-searching, or inventing facts.

## Capability Acquisition Pipeline

`Acquire runtime capability` now enters an explicit pipeline:

1. `CapabilityAcquisitionRouter`
2. `CapabilityIdentityExtractor`
3. `TemplateResolver`
4. `LLMCapabilityPlanner`
5. `WebEvidenceRetriever`
6. `ArtifactGenerator`
7. `SandboxValidator`
8. `CapabilityMatchContract`
9. `RegistryWriter`

The identity contract extracted from the user request is carried through the whole lifecycle. When no template matches, a runtime-configured planner hook can be supplied through `AI_CORE_CAPABILITY_PLANNER=module.path:function_name`. The planner must return a runtime capability template that passes the neutral template contract. Low confidence, missing planner output, missing evidence, sandbox failure, or identity mismatch routes into Runtime Self-Repair.

## Capability Match Contract

Before registration, generated artifacts must satisfy the declared match contract:

- expected tool id
- expected template id
- required artifact directory name
- required markers
- forbidden markers
- schema-bearing manifest
- sandbox validation report
- verification run report

Failure produces explicit statuses such as `template_not_found`, `planner_failed`, `evidence_missing`, `sandbox_failed`, or `generated_but_capability_mismatch` instead of silently registering an incorrect capability.

## Validation commands

```bash
python validate_source_package.py
python tools/verify_runtime_config_boundary.py
python tools/verify_runtime_self_repair.py
```

## Reset local runtime data

```bash
python scripts/reset_runtime_data.py --yes
```

To also remove runtime-generated artifacts, traces, checkpoints, and deliveries:

```bash
python scripts/reset_runtime_data.py --yes --include-runtime-generated
```

## v15.9 local model default update

- Added Qwen3.5 2B Instruct and Qwen3.5 4B Instruct to the local model catalog.
- Default local model is now `qwen3.5:2b-instruct`.
- `qwen3.5:4b-instruct` is used as the first stronger local fallback for planning stages.
- Existing qwen3:8b remains available as a later fallback, not as the default.


## v15.11 Ollama GGUF Import Support

- Ollama model preparation now supports a pull-then-GGUF-import fallback.
- When an Ollama tag is missing, the runtime can resolve a configured local GGUF path or GGUF URL, generate a Modelfile, and call `ollama create <model> -f <Modelfile>`.
- Configure local GGUF files with environment variables such as `AI_CORE_QWEN35_2B_GGUF_PATH` or URLs with `AI_CORE_QWEN35_2B_GGUF_URL`.
- GGUF import is runtime model lifecycle support; it is not business capability logic.
