# v59 Runtime Autonomous Codegen Executor

## Goal

Close the runtime loop after a module/tool blueprint is generated.

Previous behavior:

```text
missing capability
→ blueprint generated
→ codegen_request written
→ workflow stopped at missing_tool_implementation
```

v59 behavior:

```text
missing capability
→ blueprint generated
→ codegen_request read automatically
→ strong model code generation
→ module.py generated
→ sandbox validation
→ registry enabled
→ workflow resumes
→ module executes
```

## Added

- `ai_core/modules/autonomous_codegen_executor.py`
  - Reads pending runtime module codegen request files.
  - Calls configured strong-model/code-generation route.
  - Generates runtime module artifacts.
  - Runs sandbox verification before registration.
  - Enables registry only after validation succeeds.
  - Writes successful solutions to runtime knowledge.

- `VerifiedSandboxRuntime.verify_module_artifact(...)`
  - Verifies `module.py` / `run(...)` module artifacts with the existing generic sandbox path.

- Tool execution integration
  - When a generated module blueprint contains a pending codegen request, execution no longer stops immediately.
  - It tries autonomous codegen, then reloads and executes the enabled module.

- `scripts/smoke_test_v59.py`
  - Tests the autonomous codegen lifecycle with a fake model generator.

## Safety

- No domain-specific words or decisions were added to `ai_core`.
- Codegen remains capability-agnostic.
- Generated modules are sandbox-tested before registry enablement.
- Failed codegen or sandbox validation does not register executable modules.

## Validation

```text
compileall: OK
smoke_test.py: OK
smoke_test_v54.py: OK
smoke_test_v55.py: OK
smoke_test_v56.py: OK
smoke_test_v57.py: OK
smoke_test_v58.py: OK
smoke_test_v59.py: OK
semantic boundary scanner: OK / disabled when policy missing
```
