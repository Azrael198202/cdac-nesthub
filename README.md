# CDAC NestHub - AI Runtime OS Source Clean

## Version
V2.8.2 Clean Source + Working Agent Studio

## Design Boundary

- `ai_core/` is the primary runtime brain and execution kernel.
- `auxiliary_brain/` is a parallel companion brain for agent, task, and community management.
- `apps/` contains API and UI source code, including Agent Studio.
- `runtime/` is a runtime workspace and is intentionally empty in source packages.

## Runtime Workspace

The source package keeps only:

```text
runtime/.gitkeep
```

Runtime-generated agents, tasks, traces, deliveries, checkpoints, tool bindings, semantic packs, and registries must be created during execution and must not be committed into the source package.

## Agent Studio

Start the API server and open:

```text
http://127.0.0.1:8000/agent-studio
```

Agent Studio is source code and is preserved in this package.

## Execution Responsibility

The companion brain manages definitions and dispatch metadata. The primary brain performs parsing, intent analysis, workflow construction, tool selection, execution, evidence handling, and final synthesis.

## Clean Source Rules

- Do not place concrete runtime artifacts in source.
- Do not hard-code domain-specific logic in `ai_core/` or `auxiliary_brain/`.
- Put concrete profiles, tools, and generated schemas under `runtime/` during execution only.
