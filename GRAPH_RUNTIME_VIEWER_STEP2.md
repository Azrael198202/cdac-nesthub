# Step 2: Graph Runtime Viewer

## Implemented scope

This step adds a dedicated runtime graph visualization surface without changing business execution logic.

## New backend capability

- `ai_core/graph/graph_visualization.py`
  - Converts runtime graph data into a UI-ready DAG snapshot.
  - Supports structural node states: `pending`, `running`, `completed`, `failed`, `skipped`, `reused`, `repair`, and `metadata_only`.
  - Builds topological lanes so the UI can show parallel and serial execution.
  - Derives edges from explicit edges or `depends_on` when explicit dataflow is missing.
  - Collects runtime events and repair plans for display.

## New API endpoints

- `GET /graph-runtime`
  - Opens the new visualization page.

- `GET /api/graph-runtime/state`
  - Returns the latest graph state from Agent Studio runtime snapshots.
  - Optional query: `graph_id`.

## New UI page

- `apps/web/graph_runtime.html`
  - Displays DAG lanes.
  - Shows animated dataflow edges.
  - Shows status badges for nodes.
  - Shows runtime events.
  - Shows repair plan items.
  - Auto-refreshes while execution is active.

## Agent Studio integration

- Added a `Graph Runtime` link on the Agent Studio page.
- Users can execute tasks in Agent Studio and open the graph viewer to observe dataflow.

## Validation

Added tests:

- `tests/test_graph_visualization_state.py`

Validated with:

```bash
pytest -q
```

Result:

```text
48 passed
```

## Current limitation

This page visualizes the latest runtime graph snapshot. The next improvement should stream graph events directly while execution is running, instead of relying only on polling snapshots.
