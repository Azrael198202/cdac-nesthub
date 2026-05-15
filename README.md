# CDAC NestHub v70.16

Runtime answer evidence extraction fix.

## Changes

1. `fetch_selected_pages` now captures visible text, compact HTML evidence, and DOM attribute evidence.
2. Answer sufficiency checks include `html_excerpt`, `dom_evidence_text`, and DOM attributes such as `title`, `alt`, `aria-label`, `datetime`, `href`, and `data-*`.
3. Calendar/card/table style pages can satisfy runtime variables when the answer is present in HTML attributes rather than plain text.
4. Direct evidence fallback also reads HTML/DOM evidence.
5. Keeps v70.15 multilingual semantic sufficiency logic and v70.14 fetch-before-API/tool discovery flow.

## Packaging

Runtime-generated artifacts, traces, caches, and transient directories are excluded from the ZIP package.
