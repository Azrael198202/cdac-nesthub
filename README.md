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

## Next Target: V2.2

V2.2 should connect these contracts into the actual end-to-end `WorkflowRuntime` path, so normal user requests automatically pass through decomposition, parallel retrieval, evidence verification, route/sequence optimization, and stable synthesis.
