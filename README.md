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
- Default local model is now `qwen3.5:2b`.
- `qwen3.5:4b-q4_k_m` is used as the first stronger local fallback for planning stages.
- Existing qwen3:8b remains available as a later fallback, not as the default.


## v15.11 Ollama GGUF Import Support

- Ollama model preparation now supports a pull-then-GGUF-import fallback.
- When an Ollama tag is missing, the runtime can resolve a configured local GGUF path or GGUF URL, generate a Modelfile, and call `ollama create <model> -f <Modelfile>`.
- Configure local GGUF files with environment variables such as `AI_CORE_QWEN35_2B_GGUF_PATH` or URLs with `AI_CORE_QWEN35_2B_GGUF_URL`.
- GGUF import is runtime model lifecycle support; it is not business capability logic.


## v15.12 Qwen3.5 2B Default and Direct GGUF Import

- Default local Ollama model is now `qwen3.5:2b`.
- Added explicit GGUF-backed local model ids: `qwen3.5:2b-q4_k_m` and `qwen3.5:4b-q4_k_m`.
- The runtime does not alias or silently map `qwen3.5:2b` to another model.
- When a selected model has a configured GGUF path or URL, Ollama preparation imports the GGUF first with `ollama create` instead of wasting time on a pull that cannot exist.
- Preferred GGUF filenames are `Qwen3.5-2B-Q4_K_M.gguf` and `Qwen3.5-4B-Q4_K_M.gguf`.

## v15.13 External GGUF Auto Resolver

This version adds a generic external runtime model resolver for GGUF files.
When a local Ollama model is missing and the selected model is a GGUF-backed
model, the runtime now checks `runtime/external_runtimes/models/` first. If no
local GGUF file is found, it resolves a Hugging Face direct download URL and
stages the file under `runtime/external_runtimes/models/<model_id>/` before
creating the Ollama model with `ollama create`.

Default Q4_K_M sources:

- `qwen3.5:2b-q4_k_m` → `Qwen3.5-2B-Q4_K_M.gguf`
- `qwen3.5:4b-q4_k_m` → `Qwen3.5-4B-Q4_K_M.gguf`

The normal `qwen3.5:2b` Ollama tag remains available and is not remapped.
