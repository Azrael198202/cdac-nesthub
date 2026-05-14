# v68 Endpoint Resolution + Parallel Candidate Runtime

## Implemented

1. Endpoint verification no longer treats documentation pages as executable API base URLs.
2. Runtime endpoint resolver extracts executable URL candidates from HTML text, OpenAPI/Swagger-style links, request examples, and relative API paths.
3. Relative API paths are verified against both documentation host and generic `api.<host>` host variants.
4. Static verification failure no longer has to block the workflow immediately; execution can continue through candidate evaluation.
5. Missing or invalid `run(payload)` contract triggers deterministic adapter fallback.
6. Generated tool contract checking is strengthened before sandbox registration.
7. Execution provenance and runtime events use safe JSON paths already present in the runtime.
8. `ai_core` remains domain-neutral: no business-specific routing tables or fixed provider mappings are added.
9. Sequential fallback is upgraded to no-key-first parallel candidate evaluation with result synthesis.
10. Runtime successful strategies are persisted under `runtime/knowledge/successful_strategies.jsonl`.
11. Generated adapters remain reusable through the runtime registry once sandbox-verified.
12. Provider reliability observations are recorded under `runtime/knowledge/provider_reliability.jsonl`.
13. Dynamic tool graph optimization is prepared through candidate scoring, reliability records, and successful strategy reuse.
14. Autonomous capability composition remains driven by runtime candidates, generated adapters, and verified modules.
15. Self-healing execution plans continue after candidate/tool failures instead of stopping at the first failed candidate.
16. Runtime evidence quality is used to choose or reject candidate results before final answer synthesis.

## Notes

Runtime-generated files, traces, downloads, caches, and transient knowledge are intentionally excluded from source ZIP packages.
