# Execution Method Contract and Deep Web Research Pipeline

## Purpose

This version separates execution method selection into three layers:

1. **Execution Method Proposal**
   - Workflow/model output may propose candidate methods.
   - Supported method names are generic: `runtime_generated_tool`, `existing_tool`, `web_search`, `knowledge_base`, `model_knowledge`, and `api_call`.

2. **Deterministic Runtime Decision**
   - The runtime resolver makes the final decision from capability registry, source policy, schema contracts, and execution context.
   - LLM output is proposal only; it cannot directly force a method.

3. **Execution Contract**
   - Every resolved method carries input schema, output schema, confidence, cost, latency, and fallback.

## Deep Web Research Pipeline

`web_search` now follows a DeepSearch / DeepResearch style pipeline:

```text
query/candidate planning
→ candidate ranking
→ incremental page fetching
→ multi-layer extraction
→ DOM/table/list extraction
→ adaptive evidence reduction
→ normalized facts
→ compact answer material
```

The extractor uses optional libraries when available:

- `BeautifulSoup`
- `lxml`
- `trafilatura`
- `pandas.read_html`

If optional libraries are not installed, it falls back to generic structural text extraction.

## Quality Guard

Raw webpage text is not promoted to final answer merely because it contains a known parameter. The system requires structured facts or compact answer material generated from structured extraction.

## Generic Rule

No business/domain/task keywords are hard-coded in the new source files. Runtime variables, schemas, capability contracts, and extracted structure drive decisions.
