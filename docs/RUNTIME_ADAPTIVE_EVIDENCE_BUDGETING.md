# Runtime Adaptive Evidence Budgeting

This version replaces simple page/text hard limits with an adaptive evidence reduction pipeline.

## Goal

Cost control must reduce expensive model input, not reduce answer quality by blindly cutting sources.

The runtime now follows this path:

```text
candidate sources
  -> local ranking and source diversification
  -> incremental fetch
  -> local DOM/text normalization
  -> fact extraction
  -> deduplication
  -> compact material building
  -> quality-based early stop
  -> final synthesis uses compact facts, not raw HTML
```

## Design rules

- No domain or business keywords are embedded.
- The reducer uses only runtime-provided parameters, aliases, numeric/unit structure, source diversity, and evidence quality.
- Expensive API models should receive compact `normalized_facts` and `answer_material`, not raw pages.
- The fetch process can stop early only when compact evidence quality is sufficient.
- If quality is not sufficient, it expands incrementally until the adaptive budget is exhausted.

## Main modules

```text
ai_core/runtime/evidence/evidence_budget.py
ai_core/runtime/evidence/evidence_reducer.py
ai_core/runtime/evidence/evidence_normalizer.py
```

## Configuration

```json
{
  "adaptive_evidence": {
    "enabled": true,
    "min_sources": 2,
    "max_sources": 5,
    "candidate_window": 6,
    "initial_fetches": 2,
    "incremental_fetches": 1,
    "max_fetches": 5,
    "fetch_chars_per_source": 18000,
    "llm_material_chars": 6000,
    "fact_limit": 48,
    "block_limit": 32,
    "stop_quality_score": 0.78
  }
}
```

The legacy `max_evidence_pages` and `max_evidence_page_chars` remain as backward-compatible budget fields, but the runtime now treats them as adaptive budget ceilings rather than direct quality truncation rules.
