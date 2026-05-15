# CDAC NestHub v70.2

## Runtime Role-Scoped Prompt Optimization

This version continues the v70 code line and pauses the v2.1 Runtime Integration OS branch.

## Main Goal

Reduce LLM prompt size and runtime latency by selecting a compact runtime role immediately after intent/context signals are available. Downstream nodes receive only role-scoped context instead of full workflow traces, raw web pages, endpoint checks, and discovery payloads.

## New Components

```text
ai_core/roles/
  role_profile_selector.py
  prompt_pack_loader.py
  role_scoped_context_reducer.py

runtime/configs/roles/
  prompt_packs.yaml
```

## Runtime Flow

```text
input_parsing
  ↓
intent_recognition
  ↓
RoleProfileSelector
  ↓
PromptPackLoader
  ↓
RoleScopedContextReducer
  ↓
LLM node execution with compact prompt
```

## Generic Runtime Roles

- information_retrieval_agent
- code_generation_agent
- document_writer_agent
- data_analysis_agent
- integration_builder_agent
- human_interaction_agent
- workflow_planning_agent
- general_runtime_agent

These are generic runtime roles, not business/domain agents.

## What Changed from v70.1

1. Added role profile selection before LLM prompt rendering.
2. Added role-specific prompt packs and runtime rules.
3. Added role-scoped context reduction.
4. Replaced full `previous_results` with compact role-scoped results.
5. Replaced full `capability_result` with compact role-scoped result.
6. Added compact `evidence_summary` to runtime context.
7. Added role-based prompt budget override.
8. Prevented raw discovery JSON, full HTML, endpoint checks, and trace paths from entering ordinary LLM prompts.
9. Added a regression test for role-scoped context reduction.

## Expected Improvements

- Lower prompt token usage.
- Lower OpenAI/vLLM/Ollama latency.
- Fewer timeout cases after sandbox fallback.
- More stable fallback generation.
- Cleaner LLM inputs.
- Better separation between intent role and execution prompt.

## Packaging Policy

The source package keeps framework/source files and excludes runtime artifacts:

```text
runtime/generated/
runtime/cache/
runtime/traces/
runtime/tmp/
runtime/downloads/
__pycache__/
.pytest_cache/
*.pyc
```

Only the current version README is kept.
