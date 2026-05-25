# Step 15: Stage-aware workflow planning and stable dataflow execution

This update fixes regressions where a numbered multi-step task was collapsed into unclear participant nodes or allowed downstream dataflow to run before all declared upstream nodes were ready.

## Changes

- Numbered workflow fragments are split into separate structural steps.
- Participant nodes keep concise graph labels and no longer display the full task text as their node objective.
- Sequenced generated steps without direct participant references are preserved as downstream dataflow nodes.
- Generated step dependencies are resolved through source step ids, task ids, and participant ids.
- The expected stage shape is preserved:
  - Stage 1: independent participant execution nodes.
  - Stage 2: dataflow transform nodes that depend on all required upstream outputs.
  - Stage 3: final projection / return nodes that depend on the transform result.
- Short participant ids are no longer matched inside ordinary words.

## Validation

```bash
PYTHONPATH=. pytest -q
# 77 passed
```
