# CDAC NestHub - AI Runtime OS Source Clean

This package is a source-only clean build.

## Included
- Generic source code for the AI Runtime OS kernel.
- Generic auxiliary brain / coordination source when present.
- Application source, schemas, scripts, tests, and base configuration.

## Excluded
- Runtime generated agents, tasks, workflows, traces, deliveries, checkpoints, cache, datasets, learned registries, downloaded artifacts, generated schemas, and runtime YAML state.
- Python cache and test cache files.

## Design rule
Core source must remain domain-agnostic. Domain-specific behavior, semantic surface packs, tool bindings, workflows, agents, tasks, and environment-specific runtime state must be generated under `runtime/` during execution, not committed as source.
