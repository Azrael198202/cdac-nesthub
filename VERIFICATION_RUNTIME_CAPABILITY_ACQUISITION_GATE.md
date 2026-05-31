# Runtime Capability Acquisition Gate Verification

## Goal

Abstract runtime-generated tool registration into one generic gate so that any generated capability must pass the same lifecycle before it can be enabled:

1. implementation artifact generated
2. dependency decision passed
3. capability match contract passed
4. sandbox/static validation passed
5. verification run passed
6. registry updated only after the gate returns `safe_to_register=true`

## Generic design

Added:

- `ai_core/runtime/capability/acquisition_gate.py`

The gate is domain-neutral. It does not know SMTP, mail, browser, weather, files, or any concrete business capability. It only evaluates runtime-declared contracts and validation outputs.

## Integrated paths

### Autonomous capability acquisition

Updated:

- `ai_core/capabilities/runtime_capability_gap_implementer.py`

The implementer now calls the gate before validation and again before registry enablement. A generated artifact can no longer be registered only because files were written.

### Runtime-generated tool installer

Updated:

- `ai_core/tools/runtime_generated_tool_installer.py`

The installer now performs:

- capability match contract verification
- generic sandbox verification through `VerifiedSandboxRuntime`
- registration gate check
- registry write only if `safe_to_register=true`

This also covers primitive-template-generated tools because they pass through the same installer.

## Verification performed

### Compile check

```text
python -m compileall -q ai_core apps auxiliary_brain
result: passed
```

### SMTP autonomous acquisition check

```text
status: implemented_tested_registered
registration_gate.status: registration_gate_passed
registration_gate.safe_to_register: true
validation.passed: true
verification_run.passed: true
registration: true
```

### Generic generated tool installer check

A non-domain echo tool artifact was installed through the installer:

```text
tool_id: gate_sample_echo_tool
status: enabled
registration_gate.status: registration_gate_passed
registration_gate.safe_to_register: true
```

### Capability mismatch blocking check

A generated tool with an unsatisfied required marker was blocked:

```text
ValueError: Generated runtime tool artifact failed acquisition gate: Generated artifact did not satisfy its declared capability match contract.
```

## Result

The SMTP case still works, and the same gate now protects other runtime-generated tools. This is not SMTP-specific logic; it is a shared runtime acquisition gate.
