# AI Core Runtime v34 - Real Weather Tool Runtime

## Version Goal

v34 upgrades the continuation runtime so the system can execute a real read-only runtime tool.

Main target:

```text
weather_api capability -> runtime registered tool -> Open-Meteo API call -> result written back to execution state
```

Flight booking remains intentionally blocked behind missing information and human confirmation. v34 does not perform booking, payment, or external mutation.

---

## What Changed from v32

### 1. Generic Tool Runner

Added:

```text
ai_core/tools/generic_tool_runner.py
```

Responsibilities:

```text
- read runtime tool implementation metadata
- dynamically load Python tool file
- call configured function
- return generic tool result
```

The runner does not know any business/domain concepts.

---

### 2. ToolCallExecutor Executes Registered Tools

Updated:

```text
ai_core/executors/tool_call_executor.py
```

Previous behavior:

```text
ready step -> mark ready_to_execute
```

New behavior:

```text
ready step -> find runtime tool -> execute tool -> write result into execution_steps
```

---

### 3. Runtime Tool Registry Prefers Enabled Implementations

Updated:

```text
ai_core/tools/runtime_tool_registry.py
```

If multiple specs exist for the same capability, registry selection now prefers:

```text
enabled / active / approved / ready
+ implementation.module_path exists
```

This prevents old blueprint-only specs from hiding a real implementation.

---

### 4. Open-Meteo Weather Tool

Added runtime tool:

```text
runtime/generated/tools/open_meteo_weather_tool/
├── tool.py
├── tool.json
└── README.md
```

Registered in:

```text
runtime/registry/tool_registry.json
```

Capability:

```text
weather_api
```

Safety:

```text
read-only external API
no external write
no irreversible action
no human confirmation required
```

Provider:

```text
Open-Meteo public API
```

API key:

```text
not required
```

---

## Runtime Flow

```text
workflow_planning
↓
workflow_normalizer
↓
required_capability = weather_api
↓
runtime tool registry
↓
open_meteo_weather_tool
↓
GenericToolRunner
↓
Open-Meteo geocoding + forecast API
↓
execution result
```

---

## Smoke Tests

```bash
python3 scripts/smoke_test.py
python3 scripts/smoke_test_weather_tool.py
python3 -m compileall -q .
```

`smoke_test_weather_tool.py` uses:

```text
WEATHER_TOOL_OFFLINE_MOCK=1
```

so it can run without internet access. Normal runtime execution does not use mock mode unless this environment variable is set.

---

## Real Weather Example

Input workflow step:

```json
{
  "task_id": "1",
  "task_type": "weather.forecast.query",
  "action": "check_weather_forecast",
  "parameters": {
    "known": {
      "location": "Tokyo",
      "date": "tomorrow"
    },
    "missing_required": {},
    "optional": {}
  },
  "execution_ready": true,
  "requires_human_confirmation": false
}
```

Expected execution state:

```json
{
  "status": "executed",
  "execution_steps": [
    {
      "step_id": "1",
      "status": "executed",
      "result": {
        "status": "success",
        "source": "open_meteo",
        "requires_human_confirmation": false,
        "data": {
          "location": {},
          "date": "YYYY-MM-DD",
          "forecast": {}
        }
      }
    }
  ]
}
```

---

## Boundary Principle

`ai_core` still does not contain weather-specific logic.

Weather-specific behavior exists only in:

```text
runtime/generated/tools/open_meteo_weather_tool/
runtime/registry/tool_registry.json
```

This keeps the core aligned with the architectural rule:

```text
ai_core = generic runtime orchestration kernel
runtime = generated intelligence and capability layer
```
