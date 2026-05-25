# Step 13: Dependency Result Validity Gate

## Implemented

- Added a generic result-material validity gate for delegated graph execution.
- A node with `status=completed` is no longer considered usable unless it also has verified user-facing result material.
- Generic blocked, waiting, unavailable, and non-execution placeholders are rejected as upstream material.
- Dependent nodes are skipped before execution when required upstream material is missing or invalid.
- Downstream dataflow steps receive only verified upstream summaries.
- Primary-runtime participant status extraction now prioritizes pending input state and rejects completed states without public result material.

## Why

This prevents a graph from continuing when an upstream node only returned a blocked/waiting placeholder. The graph now fails earlier and more accurately:

- invalid upstream result → normalized to failed
- dependent node → skipped
- final synthesis → receives explicit failure/skipped material instead of partial fake success

## Validation

```bash
pytest -q
# 73 passed
```
