# Source / Runtime Boundary Packaging Fix

This package preserves source modules under `ai_core/runtime/**` and excludes only runtime-generated artifacts under the project-root `runtime/**` working directory.

Preserved:
- `ai_core/**/*.py`
- `apps/**/*.py`
- `auxiliary_brain/**/*.py`
- `configs/**`
- `schema/**`
- `docs/**`
- runtime registries required for bootstrapping

Excluded:
- `__pycache__/**`
- `*.pyc`
- runtime generated result files
- runtime traces/checkpoints/cache/temp/sandbox/secrets

Important: `ai_core/runtime/trace_writer.py` is source code and must not be removed by clean packaging.
