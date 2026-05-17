# CDAC NestHub Runtime

## Version

V2.1

## Positioning

V1.0 / v70.29 was the first working prototype. V2.1 starts the upgrade path toward a universal runtime architecture. The core rule remains unchanged: `ai_core` must stay domain-neutral. Runtime-generated files, temporary traces, caches, and learned artifacts belong under `runtime/` and are not packaged as source.

## V2.1 Implementation Goals

1. Add a generic Task Decomposition Graph foundation.
2. Support query decomposition into neutral sub-tasks.
3. Support parallel retrieval orchestration through pluggable retrievers.
4. Add strict multi-source evidence verification with confidence scoring.
5. Add route optimization based on quality, reliability, latency, and cost.
6. Add generic sequence synthesis for ordered response or execution planning.
7. Add stable synthesis that blocks debug or trace material from final answers.
8. Add runtime-generated schema contracts for workflow structure, trace structure, and fact graph schema.
9. Add a browser runtime contract for session reuse, wait policy, network capture, screenshot evidence, and materialized evidence output.
10. Add a transport-neutral Universal MCP Runtime facade.
11. Add a bounded self-healing runtime contract based on generic failure taxonomy.
12. Add deterministic runtime tests and execution assertions for the new contracts.
13. Clear runtime-generated contents from the source package.

## V2.1 Added Source Modules

```text
ai_core/runtime/tasking/task_decomposition_graph.py
ai_core/runtime/retrieval/parallel_retrieval.py
ai_core/runtime/evidence/evidence_verifier.py
ai_core/runtime/routing/route_optimizer.py
ai_core/runtime/aggregation/sequence_synthesizer.py
ai_core/runtime/aggregation/stable_synthesizer.py
ai_core/runtime/schemas/runtime_schema_generator.py
ai_core/runtime/browser/playwright_browser_runtime.py
ai_core/runtime/mcp/universal_mcp_runtime.py
ai_core/runtime/repair/self_healing_runtime.py
tests/runtime/test_v21_runtime_upgrade.py
```

## Runtime Directory Rule

The packaged `runtime/` directory is intentionally empty except `.gitkeep`. During execution, the application may generate configs, traces, caches, schemas, tools, adapters, checkpoints, and learning records under `runtime/`. These generated files should not be committed into the source package.

## Verification

```text
PYTHONPATH=. python -m compileall ai_core tests: OK
PYTHONPATH=. pytest tests/runtime/test_v21_runtime_upgrade.py tests/verification/test_v70_27_stability_verification.py tests/verification/test_v70_28_evidence_short_circuit.py tests/verification/test_v70_29_final_synthesis_and_credentials.py tests/test_v70_2_role_scoped_prompting.py: OK
```

## User Test Scenarios for V2.1

### Test 1: Multi-part information request

Question:

```text
紹介対象を複数観点で整理し、1日の流れにまとめてください。
観点: 主要項目、評価、相対距離、利用可能時間、順序最適化、食事候補、時間配分
```

Expected runtime behavior:

```text
1. The runtime creates seven independent retrieval/computation sub-tasks.
2. The first batch can run in parallel.
3. The final synthesis task depends on all seven sub-tasks.
4. Evidence verification reports source_count, coverage_ratio, and confidence.
5. Final synthesis does not expose raw traces or debug markers.
```

### Test 2: Evidence contract failure

Question:

```text
1つの情報源だけで回答せず、複数の根拠が足りない場合は不足として扱ってください。
```

Expected runtime behavior:

```text
1. Evidence verification fails or lowers confidence when source diversity is insufficient.
2. The result includes issue code insufficient_source_diversity.
3. Synthesis reports low confidence instead of pretending verification succeeded.
```

### Test 3: Runtime-generated schema validation

Question:

```text
今回の処理に必要な workflow、trace、fact graph の構造を実行時に作って検証してください。
```

Expected runtime behavior:

```text
1. The runtime produces neutral JSON schema contracts.
2. Workflow graph, trace events, and fact graph objects validate against those schemas.
3. No domain-specific schema fields are required by core code.
```

## V2.1.1 Hotfix - Non-blocking Refinement Repair

### Problem Found

A generated workflow could stop before tool execution when the planner classified refinement information as mandatory human input. Example output:

```text
status: blocked
executed_steps: 0
blocked step: collect_missing_info
reason: execution_ready is false
missing_required: field_alpha, field_beta
```

### Fix Implemented

1. Added a domain-neutral execution-state repair rule.
2. For read-only steps, missing refinement fields are moved from `missing_required` to `optional` by structural policy, not by business-specific names.
3. If no truly blocking field remains, the step is marked `execution_ready=true`.
4. Non-actionable `human_interaction` metadata is changed to `required=false`.
5. Irreversible/action steps still require confirmation or required inputs when structurally necessary.

### Updated Source

```text
ai_core/workflow/execution_state_repair.py
tests/runtime/test_v21_1_non_blocking_information_repair.py
```

### Verification

```text
PYTHONPATH=. pytest -q
22 passed
```

### User Test Question

```text
请介绍某个地点，并整理一个一天内的访问计划。
```

Expected behavior after this fix:

```text
1. Runtime must not stop at collect_missing_info only because refinement fields are missing.
2. Refinement fields are treated as optional unless the step performs an irreversible action or explicitly requires confirmation.
3. Runtime should continue to retrieval/planning/synthesis steps.
4. Final answer should state any assumed defaults instead of blocking.
```

## Next Target: V2.2

V2.2 should connect these contracts into the actual end-to-end `WorkflowRuntime` path, so normal user requests automatically pass through decomposition, parallel retrieval, evidence verification, route/sequence optimization, and stable synthesis.


## V2.1.2 Update - Evidence Alignment and Semantic Boundary Hardening

### Goal

Prevent low-relevance pages from being selected only because they contain a runtime variable and many numbers. Keep ai_core domain-neutral by removing hard-coded business/task vocabulary from repair and provenance paths.

### Implemented

1. `AnswerSufficiencyEvaluator` now requires lexical alignment between the original request/objective and evidence text. Numeric density alone no longer proves sufficiency.
2. Short opaque values that do not appear in the original request/objective are ignored as probable extraction artifacts during sufficiency checks.
3. `EvidenceDirectAnswerBuilder` now ranks candidates by runtime-variable coverage plus request/evidence alignment, preventing unrelated evidence from winning only by coverage.
4. `StructuredFactNormalizer` converts extraction-debug material into sanitized user material before fact extraction and does not expose debug labels as facts.
5. `ExecutionStateRepair` no longer hard-codes concrete refinement field names in ai_core. Read-only continuation is handled structurally.
6. `ExecutionProvenanceRecorder` now records elapsed-time metadata with a neutral key that cannot be confused with user request variables.
7. Runtime generated content remains cleared; only `.gitkeep` is kept.

### Verification

```text
PYTHONPATH=. pytest -q
22 passed
```

### User Test Question

```text
请介绍某个地点，并整理一个一天内的访问计划。
```

Expected behavior:

```text
1. The system should not use unrelated pages merely because the location name appears.
2. Evidence must align with the request terms and requested output structure.
3. If the top candidate is off-topic, it should be rejected or down-ranked.
4. If evidence is insufficient, runtime should retry retrieval or continue discovery instead of producing a false negative answer.
```

## V2.1.3 Update - Compact Runtime Value Surface Normalization

### Goal

Prevent compact machine-format values from being used as direct semantic evidence terms. Runtime may still receive compact temporal values, but ai_core must convert them to user-surface terms or drop them from evidence matching when the user did not provide a matching surface form.

### Implemented

1. Added `RuntimeTemporalSurfaceNormalizer`, a domain-neutral utility for compact temporal value handling.
2. Compact temporal tokens are no longer matched directly against evidence text.
3. When the original request contains a matching surface form, the compact value is converted to that surface form before known-parameter coverage and direct-answer synthesis.
4. When the original request does not contain a matching surface form, the compact value is ignored as unsafe for semantic evidence coverage.
5. Evidence aliases use non-compact surface variants only.
6. Updated sufficiency evaluation, direct evidence answer building, evidence noise reduction, and fact graph coverage to share this normalization rule.
7. Runtime generated content remains cleared; only `.gitkeep` is kept.

### Verification

```text
PYTHONPATH=. pytest -q
29 passed
```

### User Test Question

```text
Please prepare a 3-day plan for AlphaPlace with ordered stops.
```

Expected behavior:

```text
1. The runtime must not treat the compact value as a user-facing semantic term.
2. Evidence containing only the compact token should not satisfy the period requirement.
3. Evidence containing the request-surface form should satisfy the period requirement.
4. Final data should expose the surface value rather than the compact token.
```

## V2.4 Update - Runtime-Generated Semantic Surface Packs

### Goal

Move fixed semantic surface knowledge out of `ai_core`. Core should not keep built-in unit or calendar vocabularies such as fixed temporal units. Instead, runtime analyzes the request and generated values, then creates semantic surface packs under `runtime/generated/semantic_packs/` when such handling is needed.

### Implemented

1. Removed `ai_core/utils/temporal_surface.py`.
2. Added `ai_core/utils/semantic_surface.py` as a generic compact-artifact normalizer.
3. Core no longer maps compact values through built-in unit-name lists.
4. Compact artifacts such as `P3D` / `P5D` are never used directly for evidence matching.
5. If the original request contains a matching surface span such as `3-day` / `5-day`, runtime uses that request-surface span.
6. If no user-surface span exists, the compact artifact is dropped from semantic coverage instead of becoming a false match.
7. Added runtime semantic pack generation under `runtime/generated/semantic_packs/`.
8. Removed fixed calendar word-list aliases from core evidence matching paths.
9. Added tests to ensure the old fixed surface module does not return and core does not contain fixed calendar word lists.
10. Runtime generated content is cleared before packaging; only `.gitkeep` is kept.

### Verification

```text
PYTHONPATH=. pytest -q
32 passed
```

### User Test Question

```text
Please prepare a 3-day plan for AlphaPlace with ordered stops.
```

Expected behavior:

```text
1. `P3D` must not be used as a direct semantic evidence term.
2. Evidence containing only `P3D` must not satisfy the runtime variable contract.
3. Evidence containing the user-surface span `3-day` may satisfy the contract.
4. The final known parameter should expose `3-day`, not `P3D`.
5. Any unit/surface knowledge needed for a specific request should be generated under runtime/generated/semantic_packs/ rather than stored as fixed core logic.
```
