# CDAC NestHub v70.14

## Answer Evidence Fetch Before API / Tool Discovery

This version refines the v70 execution pipeline after generic web research.

### Key Fixes

1. Generic web search results are no longer treated as final answer material when they only contain title/snippet/link.
2. If search results look promising but lack full page text, the runtime now fetches selected pages first.
3. Answer sufficiency is re-evaluated after fetching page content.
4. Only after fetched evidence is still insufficient does the runtime continue to API documentation discovery or tool/code generation.
5. Date matching is improved for multiple formats:
   - `2026-05-16`
   - `5/16`
   - `5-16`
   - `May 16`
   - `16 May`
   - `Sat 16`
   - `Saturday 16`
6. Month-level matches such as `May 2026` are treated as partial coverage, causing page fetch rather than failure.
7. Answer sufficiency trace now reports `next_action=fetch_selected_pages` for promising snippets.

### Execution Priority

```text
local factual knowledge / verified RAG
↓
generic web search
↓
answer sufficiency evaluation
↓
fetch selected pages if promising but incomplete
↓
answer sufficiency re-evaluation
↓
direct evidence answer if sufficient
↓
API documentation / tool generation only if still insufficient
```

### Packaging

Runtime-generated artifacts, traces, cache, metrics, and temporary files are excluded from the source ZIP.
