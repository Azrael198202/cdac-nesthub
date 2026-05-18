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

## V2.5 Home Experience Update - Agent Community Runtime

### Goal

Add an auxiliary runtime layer controlled by `ai_core` without adding business logic to `ai_core` or to the auxiliary brain runtime. The new layer lets the system create runtime-generated agents, communities, and task graphs under `runtime/generated/`.

### Implemented

1. Added a parallel generic Agent Community Runtime under `auxiliary_brain/community/`.
2. Added a generic auxiliary runtime entrypoint under `auxiliary_brain/runtime.py`, outside `ai_core`.
3. Added runtime artifact persistence:
   - `runtime/generated/agents/`
   - `runtime/generated/communities/`
   - `runtime/generated/tasks/`
4. Added neutral community definition models:
   - runtime agent definition
   - runtime community definition
   - runtime activation definition
   - runtime task definition
   - runtime task edge definition
5. Added neutral message bus for generated agents.
6. Added neutral blackboard shared state for generated agents.
7. Added task graph dispatch with dependency ordering and blocking when generated definitions are incomplete.
8. Added tests to verify generated artifact persistence, task dependency execution, blocking behavior, and no home-experience business terms in `ai_core` source files.
9. Runtime generated content is cleared before packaging; only `.gitkeep` is kept.

### Design Rule

`ai_core` and the auxiliary runtime do not contain concrete business agents. Concrete agents such as a home morning assistant, environment information collector, meal planner, reminder agent, or message sender must be generated at runtime and persisted under `runtime/generated/`.

### Verification

```text
PYTHONPATH=. python -m compileall -q ai_core tests
PYTHONPATH=. pytest -q
36 passed
```

### User Test Question

```text
Create a small runtime agent community for my morning routine. At 06:00, tell me the current time, summarize today's plan and outside conditions, and prepare a breakfast idea. At 11:30, prepare a lunch idea and send it to me as a message.
```

Expected behavior:

```text
1. ai_core should not directly implement those concrete roles.
2. The auxiliary runtime should generate agent definitions under runtime/generated/agents/.
3. The community definition should be saved under runtime/generated/communities/.
4. The activation/task graph should be saved under runtime/generated/tasks/.
5. The coordinator should dispatch generated task nodes according to dependency order.
6. Missing generated agent references should block only the affected task, not the whole runtime.
```

## V2.5 Home Parallel Auxiliary Brain Adjustment

Implementation target:

```text
ai_core/              main control brain only
auxiliary_brain/      parallel auxiliary brain runtime
runtime/generated/    shared generated artifacts
runtime/traces/       shared traces with explicit origin labels
```

Changes:

1. Moved community runtime source code out of `ai_core` and into `auxiliary_brain`.
2. Removed the auxiliary brain entrypoint from `ai_core/extensions`.
3. Added trace records with an explicit `origin` value so logs can distinguish main brain and auxiliary brain activity.
4. Kept generated agents, communities, and task graphs under the shared `runtime/generated` tree.
5. Added tests to verify that auxiliary brain code is parallel to `ai_core`, not nested inside it.

User test question:

```text
Create a generated assistant community from my request, save generated agent definitions, save the community definition, save the task graph, and show which runtime layer handled the operation.
```

Expected result:

```text
- ai_core remains the controller.
- auxiliary_brain creates and dispatches the generated community.
- runtime/generated/agents contains generated agent definitions.
- runtime/generated/communities contains generated community definitions.
- runtime/generated/tasks contains generated task graphs.
- runtime/traces/runtime_layers contains logs with origin = auxiliary_brain.
```

## V2.5 Home UI Parallel Patch - Agent Studio

### Goal

This patch keeps the original `apps/web/index.html` unchanged and adds a new UI page for the parallel auxiliary runtime.

### Added

```text
apps/web/agent_studio.html
auxiliary_brain/studio/config_loader.py
auxiliary_brain/studio/service.py
configs/agent_studio_commands.json
.vscode/launch.json
tests/runtime/test_v25home_agent_studio_ui.py
```

### Runtime Layout

```text
ai_core/              Main control brain
auxiliary_brain/      Parallel auxiliary brain
runtime/generated/    Shared generated participants, communities, task graphs, and task runs
runtime/traces/       Origin-labelled runtime layer traces
```

### UI Capabilities

```text
1. Interactive console for runtime participant creation.
2. Generated participant list.
3. Task graph, tool reference, run-state, and trace viewer.
4. Interactive console for task graph creation.
5. Start/stop controls for the latest generated task graph.
6. Command phrases are loaded from configs/agent_studio_commands.json, not embedded in source code.
7. VS Code debug configuration for FastAPI server and UI smoke test.
```

### Debug

```text
Open VS Code Run and Debug:
- Debug API Server
- Debug Smoke Test

Then open:
http://127.0.0.1:8000/agent-studio
```

### Verification

```text
PYTHONPATH=. python -m compileall ai_core auxiliary_brain apps tests: OK
PYTHONPATH=. pytest -q: 44 passed
Domain-term scan for ai_core and auxiliary_brain: no configured home-experience terms found
```

### Suggested Next Additions

```text
1. Add SSE updates for auxiliary runtime events.
2. Add per-participant execution timeline.
3. Add generated-tool artifact preview panel.
4. Add task graph visual layout instead of JSON-only view.
5. Add approval gate UI for generated actions that require human review.
```

## V2.5 Home Agent Studio UI Fix

### Goal
Improve the parallel auxiliary-brain operation page without replacing `apps/web/index.html` and without moving concrete runtime semantics into `ai_core` or `auxiliary_brain` source code.

### Changes
- Kept the original web page unchanged.
- Updated `apps/web/agent_studio.html` with a fixed, visible composer area so the send/start/stop controls are not hidden by the viewport.
- Added a thinking state for long operations; action buttons are disabled while a request is active.
- Added a runtime access input area. The source code does not embed provider-specific prompts; labels and input profiles are loaded from `configs/agent_studio_commands.json`.
- Added dynamic missing-input rendering. When the runtime returns `missing_inputs`, the page creates input fields automatically and submits them back to the runtime.
- Added `/api/agent-studio/runtime-input` for process-level runtime input acceptance.
- Runtime input markers are stored under `runtime/generated/runtime_inputs/` without storing the submitted secret value.

### Validation
```bash
PYTHONPATH=. python -m compileall -q ai_core auxiliary_brain apps tests
PYTHONPATH=. pytest -q
# 47 passed
```

### Suggested test questions
```text
create agent alpha beta
create agent alpha use external model
create task neutral objective
start task
stop task
```

Expected behavior:
- The send button remains visible.
- Sending a message changes the button/status to thinking.
- If a runtime input is required, dynamic input fields appear.
- Created agents, task graphs, task runs, and traces are visible in the right panels.

## V2.6 Runtime Execution Lifecycle

### Implementation Goals

V2.6 changes Agent Studio from a generated-graph viewer into a runnable experimental runtime. The main brain remains the controller, while the parallel auxiliary brain owns live execution lifecycle components. No domain-specific logic is added to `ai_core` or `auxiliary_brain`; concrete participant labels, task text, generated files, tool outputs, and delivery content are runtime artifacts.

### Added Runtime Capabilities

```text
1. Parse structural activation expressions into runtime activation metadata.
2. Register generated task graphs with a persistent scheduler registry.
3. Create live execution instances under runtime/instances/.
4. Dispatch due/generated tasks through the auxiliary execution runtime.
5. Run generic public discovery and synthesis tool calls.
6. Persist tool outputs under runtime/generated/tool_outputs/.
7. Deliver execution results to a console delivery channel under runtime/deliveries/.
8. Display schedules, instances, tool outputs, and deliveries in Agent Studio.
```

### Added Source Modules

```text
auxiliary_brain/scheduler/trigger_parser.py
auxiliary_brain/scheduler/scheduler_runtime.py
auxiliary_brain/execution/tool_runtime.py
auxiliary_brain/execution/execution_runtime.py
tests/runtime/test_v26_runtime_execution_lifecycle.py
```

### User Test Scenario

Input in Agent Studio, in this order:

```text
Create a time alert agent.
Create a weather forecast agent.
Create a task: Alarm woke me up at 10:10 AM and tell me the weather forecast for Fukuoka that day.
```

Expected behavior:

```text
1. Two generated participants appear.
2. A generated task graph appears with activation metadata containing trigger_type, expression, timezone, and scheduled_at.
3. A schedule record appears under runtime/generated/schedules/.
4. A live instance appears under runtime/instances/.
5. At the trigger time, the runtime dispatches generated tasks.
6. Generic tool outputs appear under runtime/generated/tool_outputs/.
7. Console delivery appears under runtime/deliveries/.
8. Trace events identify whether work was done by ai_core or auxiliary_brain.
```

### Verification

```text
PYTHONPATH=. python -m compileall ai_core auxiliary_brain apps tests: OK
PYTHONPATH=. pytest -q: 52 passed
Forbidden source term scan for ai_core / auxiliary_brain: OK
```

## V2.6.1 Runtime Timezone Fallback Fix

### Problem Fixed

On Windows Python installations, `zoneinfo.ZoneInfo` may fail when the IANA timezone database is not installed. This caused Agent Studio task creation to return Internal Server Error before the runtime could register the schedule.

### Implementation

```text
1. Added runtime-configured timezone fallback resolver.
2. Added configs/runtime_timezones.json for host-specific fallback offsets.
3. Removed locale-specific timezone fallback from source code.
4. Trigger parsing now records timezone_resolution metadata.
5. Agent Studio no longer crashes when host timezone data is missing.
```

### Added Files

```text
configs/runtime_timezones.json
auxiliary_brain/scheduler/timezone_resolver.py
tests/runtime/test_v26_1_timezone_fallback.py
```

### Verification

```text
PYTHONPATH=. python -m compileall -q ai_core auxiliary_brain apps tests: OK
PYTHONPATH=. pytest -q: 53 passed
```

### Retest Input

```text
Create a time alert agent.
Create a weather forecast agent.
Create a task: Alarm woke me up at 10:10 AM and tell me the weather forecast for Fukuoka that day.
```

Expected result: task graph creation succeeds, schedule and live instance records appear, and no `ZoneInfoNotFoundError` is raised.

## V2.6.2 Named Task Execution Fix

Goal: make Agent Studio support explicit named task creation and explicit named task execution.

Implemented:

- `Create an agent named ...` now stores a user-visible runtime label in generated agent artifacts.
- `Create a task named taskA ...` creates a task graph only; it does not execute immediately when no scheduled trigger is present.
- `execute TaskA` resolves the matching runtime-generated task graph by generated metadata and runs the live execution lifecycle immediately.
- Runtime execution now uses the full community artifact so assigned participant references resolve correctly.
- Task graph artifacts include generated metadata and generated participants for UI inspection.
- Agent Studio displays execution output through task runs, tool outputs, and console deliveries.

Manual test:

```text
Create an agent named Time Agent to remind you of the current time.
Create an agent named Weather Agent to obtain the weather information for Fukuoka today and tomorrow.
Create a task named taskA, which calls the time agent and the weather agent.
execute TaskA
```

Expected result:

- The first two commands create two generated participants.
- The third command creates `taskA` with status `created` and no delivery yet.
- The fourth command executes `taskA`, creates tool outputs, writes a delivery artifact, and displays the result in Agent Studio.

Validation:

```text
compileall: OK
pytest: 54 passed
```


## V2.6.3 Update - Named Task Output Quality

### Goal

Make named task execution visibly useful in Agent Studio. A task created by name is stored only as a graph until the user explicitly executes it. Execution now uses each runtime-generated agent instruction as the task material source, rather than searching with the graph creation sentence.

### Implemented

1. Agent definitions now persist the original runtime instruction in agent metadata.
2. Task graph creation resolves explicitly referenced agent names before lexical fallback.
3. Collect steps use agent-specific instructions as objectives.
4. Tool routing is driven by `configs/agent_runtime_tools.json`, not hard-coded business phrases.
5. Generic runtime context snapshots can produce an immediate local execution result.
6. Public discovery queries are cleaned to avoid graph/task command pollution.
7. `execute TaskA` now produces tool outputs and a console delivery that can be seen in the UI.

### User Test

```text
Create an agent named Time Agent to remind you of the current time.
Create an agent named Weather Agent to obtain the weather information for Fukuoka today and tomorrow.
Create a task named taskA, which calls the time agent and the weather agent.
execute TaskA
```

Expected result:

```text
taskA remains created until execution is requested.
execute TaskA creates a live run.
The UI shows task run, tool outputs, and a console delivery.
The result should not contain unrelated search results caused by task-creation wording.
```

## V2.6.4 Update - Main-Brain Driven Agent Execution

### Goal

Keep the auxiliary brain as a parallel community/task coordination layer, while moving actual execution responsibility back to `ai_core`.

### Implemented

1. Added `ai_core/agent_execution/` as the main-brain execution adapter for generated agent tasks.
2. `auxiliary_brain` now resolves named agents/tasks, creates task graphs, and tracks state only.
3. `execute TaskA` now calls the `ai_core` execution adapter for each task node.
4. Tool outputs now carry `origin: ai_core`.
5. Console deliveries remain stored by `auxiliary_brain`, with `upstream_origin: ai_core`.
6. Runtime traces now show both layers clearly:
   - `origin=auxiliary_brain`: task/community management and delivery storage.
   - `origin=ai_core`: task execution, material collection, and stable synthesis.
7. Source code keeps business/domain-specific terms out of `ai_core` and `auxiliary_brain`; runtime/tool routing phrases remain configuration-driven.

### User Test

```text
Create an agent named Time Agent to remind you of the current time.
Create an agent named Weather Agent to obtain the weather information for Fukuoka today and tomorrow.
Create a task named taskA, which calls the time agent and the weather agent.
execute TaskA
```

### Expected Result

```text
1. First two commands create generated participants.
2. Third command creates taskA only; it does not execute.
3. Fourth command executes taskA.
4. UI shows task runs, tool outputs, deliveries, and traces.
5. Tool outputs show origin=ai_core.
6. Delivery shows origin=auxiliary_brain and upstream_origin=ai_core.
```

### Validation

```text
compileall: OK
pytest: 56 passed
forbidden business keyword scan in ai_core / auxiliary_brain: OK
runtime: cleared before package
```
