# Generic Runtime Tool Contract

This folder may contain only generic templates/contracts. It must not contain business/domain-specific tools.

A runtime-generated tool artifact may be supplied by the runtime planning/code-generation layer using this generic shape:

```json
{
  "tool_id": "runtime_generated_tool_id",
  "capability": "capability_name_from_workflow",
  "manifest": {},
  "files": {
    "tool.py": "def run(input_data): ..."
  },
  "auto_register": true
}
```

The ai_core kernel only installs the artifact, validates the generic manifest shape, registers it, and dispatches execution.
