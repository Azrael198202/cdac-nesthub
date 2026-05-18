# CDAC NestHub - Source Clean Build

This package contains the complete source tree with runtime-generated artifacts removed.

## Source Boundaries

- `ai_core/`: primary orchestration and execution kernel.
- `auxiliary_brain/`: parallel coordination layer for generated participants, communities, task graphs, and delivery state.
- `apps/`: API and UI entry points.
- `configs/`: generic command/runtime configuration only. Concrete domain profiles must be generated or supplied at runtime.
- `runtime/`: empty runtime workspace with `.gitkeep` placeholders only.

## Runtime Rule

Concrete user/business semantics must not be hardcoded in source. They are generated or loaded at runtime under `runtime/generated/` or deployment-specific configuration.

## Debug

Use VS Code `Debug API Server` or run the API server directly from `apps/api/server.py`.

## Validation

This build was compiled after removing runtime-generated files and scanning source/config/test files for the configured forbidden terms.
