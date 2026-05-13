# AI Core Runtime v35 - Self-Generating Runtime Baseline

## Goal

v35 changes the runtime package model from pre-bundled runtime files to a self-generating runtime.

The repository should not require pre-created files under `runtime/configs`, `runtime/generated`, `runtime/registry`, or `runtime/datasets` to start.

At startup, `RuntimeBootstrap.ensure()` creates the minimum runtime structure and generic runtime metadata.

## Key Principle

```text
ai_core = generic orchestration kernel
runtime = generated intelligence layer
extensions = approved external toolpacks outside ai_core
```

## What changed from v34

- Runtime directory is shipped almost empty: only `runtime/.gitkeep` is kept.
- `runtime/configs/*.yaml`, `runtime/generated/*.yaml`, `runtime/registry/*.json`, and `runtime/datasets/*.jsonl` are generated at runtime.
- Added a generic `RuntimeToolpackInstaller`.
- Approved toolpacks are stored outside `ai_core` and outside `runtime` under `extensions/approved_tools/`.
- During runtime bootstrap or first tool registry use, approved toolpacks are copied into `runtime/generated/tools/` and registered in `runtime/registry/tool_registry.json`.
- The Open-Meteo weather tool is now an approved external toolpack, not a pre-bundled runtime generated file.

## Why this matters

This keeps `ai_core` free from business/domain logic while still allowing real tools to be installed into runtime dynamically.

`ai_core` does not know weather semantics. It only:

1. loads generic registry metadata,
2. resolves capability strings produced by runtime planning,
3. loads a registered tool implementation,
4. passes generic input data,
5. returns generic output data.

## Real weather flow

```text
clean runtime/
↓
ToolCallExecutor or WorkflowRuntime starts
↓
RuntimeToolRegistry initializes
↓
RuntimeToolpackInstaller installs approved toolpacks
↓
runtime/generated/tools/open_meteo_weather_tool is created
↓
runtime/registry/tool_registry.json is generated
↓
weather_api capability resolves to the generated runtime tool
↓
Open-Meteo tool executes
```

## Runtime files policy

Files under `runtime/` are not source files in v35. They are generated runtime state.

Recommended git policy:

```text
runtime/**
!runtime/.gitkeep
```

