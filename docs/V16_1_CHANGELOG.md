# v16.1 Blueprint Runtime Console Explorer

## Design boundary

- `ai_core` remains a generic brain and runtime operating system.
- Concrete capabilities are not written into `ai_core`.
- Runtime-created artifacts are generated under `runtime/generated` and registered under `runtime/registry` only after validation.
- Runtime assets are fixed seeds and contracts, not business implementations.

## Changes

### Runtime Console

- Added `/api/runtime-console/stream` Server-Sent Events endpoint.
- Console UI now uses SSE instead of periodic file polling.
- Added tail-f style line rendering, auto-scroll, pause/resume, filter, search, clear, and export.
- Added menu links: New Session, Graph Runtime, Runtime Console, Runtime Explorer, Settings.

### Runtime Explorer

- Added `/runtime-explorer` page.
- Added tree/list API for runtime files.
- Added safe download and file delete APIs for runtime-owned files.

### Capability Acquisition Pipeline

- Replaced template-sized planner output with compact `BlueprintPlanner` contract.
- Planner returns only blueprint JSON.
- `ArtifactGenerator` materializes `tool.py`, schemas, approval policy, verification input, and runtime interface from the blueprint.
- Registration still requires sandbox validation and verification run.

### Web Evidence Optimizer

- Existing BeautifulSoup cleaning, structural node selection, batch selection, `batch_size=8`, and `top_k=3` are preserved.

## Verification

- `python3 tools/verify_web_cleaning_batch_optimizer.py`
- `python3 tools/verify_runtime_console.py`
- `python3 tools/verify_blueprint_capability_pipeline.py`
- Python compile check for `ai_core`, `auxiliary_brain`, `apps/api`, and capability planner seeds.
