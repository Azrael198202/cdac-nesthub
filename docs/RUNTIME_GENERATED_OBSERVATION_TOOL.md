# Runtime Generated Observation Tool

This version fixes the participant execution case where a runtime-generated plan describes an observation task but does not provide a concrete executable tool.

## What changed

- Added runtime capability inference policy:
  - `configs/runtime_capability_inference.seed.json`
  - `runtime/generated/system_topology/runtime_capability_inference.json`
- Added runtime primitive tool templates:
  - `configs/runtime_primitive_tool_templates.seed.json`
  - `runtime/generated/system_topology/runtime_primitive_tool_templates.json`
- Added generic inference loader:
  - `ai_core/runtime/capability/capability_inference.py`
- Added generic primitive tool artifact factory:
  - `ai_core/tools/runtime_primitive_tool_factory.py`
- Updated workflow normalization so a step without `required_capability` can receive a runtime-policy-inferred capability.
- Updated tool registry so a matching runtime primitive template is converted into a normal runtime-generated tool artifact, registered, then executed through `GenericToolRunner`.

## Intended flow

```text
workflow_planning step
  ↓
capability inference from runtime policy
  ↓
runtime primitive tool artifact generation
  ↓
install into runtime/generated/tools
  ↓
register into runtime/registry/tool_registry.json
  ↓
GenericToolRunner executes generated tool.py
  ↓
output synthesis receives structured result
```

## Design rule

The core does not hardcode the participant behavior. Semantic triggers and generated implementation templates live in runtime/config policy files and can be replaced by model-generated or human-reviewed templates later.
