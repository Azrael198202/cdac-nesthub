# v18 Phase-1 Verification Report

## Scope

v18 Phase-1 applies only the agreed boundary correction:

- Move runtime capability acquisition ownership out of `ai_core`.
- Add `NeedCapabilityEvent` in workflow planning.
- Keep `ai_core` focused on generic understanding, planning, validation, orchestration, and synthesis.
- Keep capability acquisition, artifact generation, sandbox validation, execution verification, and registry update under `auxiliary_brain`.
- Restrict Runtime Console source scanning to `runtime/logs` and `runtime/traces`.

## Architecture result

```text
User
  ↓
ai_core
  ↓ NeedCapabilityEvent
auxiliary_brain/capability_acquisition
  ↓
runtime registry / generated runtime artifacts
```

## Changed structure

```text
auxiliary_brain/capability_acquisition/
  acquisition_router.py
  blueprint_generator.py
  implementation_planner.py
  code_generator.py
  sandbox_validator.py
  execution_verifier.py
  registry_manager.py
```

`ai_core/events/need_capability_event.py` was added as the generic event contract.

## Status semantics

`implemented_tested_registered` is no longer used.

Only `registered` means a capability was truly registered after validation and execution verification.

## Runtime Console scope

`list_console_sources()` now scans only:

- `runtime/logs`
- `runtime/traces`

It excludes runtime-generated artifacts and heavy/transient directories such as external runtimes, generated tools, generated models, downloads, cache, and datasets.

The right-side console panel has `overflow-y:auto` and a fixed flex min-height so new lines can scroll normally.

## Verification commands executed

```bash
python -m compileall -q ai_core auxiliary_brain apps tools
python tools/verify_default_planner_neutrality.py
python tools/verify_runtime_capability_pipeline.py
python tools/verify_conversation_capability_acquisition.py
```

Runtime Console source-scope verification was also executed directly against `list_console_sources()` and `read_console_source()`.

## Verification result

All checks passed.
