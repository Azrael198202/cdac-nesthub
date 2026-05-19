# CDAC NestHub - AI Runtime OS Source Clean

This source package keeps the runtime workspace clean. Runtime artifacts are generated only when the server or a workflow runs.

## Agent Delegation Runtime

The auxiliary layer manages participants, task graphs, community state, and delegation status. It does not execute tools, generate code, perform retrieval, or create final answers.

The primary runtime performs each delegated participant execution and the final synthesis:

1. A user creates participants and task graphs in Agent Studio.
2. The auxiliary layer stores definitions under the runtime workspace during execution.
3. When a named task is executed, the auxiliary layer finds the selected participants.
4. Each participant request is delegated to the primary runtime.
5. The primary runtime performs parsing, intent handling, workflow planning, tool selection, execution, evidence handling, and synthesis.
6. The auxiliary layer collects participant results and sends them back to the primary runtime for final synthesis.
7. The auxiliary layer saves the delivery and exposes it to the UI.

## Run

```bash
PYTHONPATH=. uvicorn apps.api.server:app --reload --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000/agent-studio
```

## Source Clean Rule

The package keeps only source code and base configuration. Runtime workspace content is excluded from the source package.

## V2.8.2 Agent Studio Execution Policy Fix

- `/` keeps the manual review loop for direct ai_core testing.
- `/agent-studio` uses delegated non-interactive execution.
- Delegated executions auto-approve review and confirmation gates inside ai_core.
- Secret/key or required-input pauses are returned to Agent Studio as `missing_inputs`.
- auxiliary_brain remains limited to agent/task/community management, delegation coordination, state persistence, and delivery storage.
- ai_core remains responsible for input parsing, intent recognition, workflow planning, tool selection, execution, evidence handling, and synthesis.

## V2.8.3 Agent Studio Secret Save

- Agent Studio missing-input prompt now shows `Save & Continue` and `Save` buttons.
- Pressing Enter in the secret input saves the value and retries the pending instruction.
- Secrets are written to `runtime/configs/secrets/secrets.json` through the existing `SecretStore`.
- Root `/` approval workflow remains unchanged.

## V2.8.4 Safe Subprocess Output Decode

- Fixed Windows subprocess output decoding crash when external commands emit UTF-8 or mixed bytes under cp932 locale.
- Added ai_core/utils/safe_subprocess.py.
- Replaced text-mode subprocess.run calls with UTF-8 + errors='replace' wrapper.
- Agent Studio auto-approve behavior is unchanged.
- Runtime workspace is kept source-clean; only runtime/.gitkeep is included.
## V2.8.5 Agent Studio Missing Input UX

- Agent Studio missing input prompt now shows only `Save & Continue`.
- Pressing Enter in the secret input triggers `Save & Continue`.
- After a secret is saved, the missing-input card is removed.
- A green confirmation card remains to indicate the secret has been saved.
- Runtime workspace remains source-clean; only `runtime/.gitkeep` is packaged.


## V2.8.6 Agent Studio Execution Progress UI

- Agent Studio status now shows animated running/saving states.
- Sending a message starts polling `/api/agent-studio/state` while the request is executing.
- Delegation runs now persist `current_stage` and `progress_events` so the UI can show where execution is working.
- The auxiliary layer still records coordination state only; delegated work remains owned by the primary runtime.
- Runtime workspace is kept clean in source packages and only contains `runtime/.gitkeep`.

## V2.8.7 Agent Studio Debug UX and Resume

- Added copy buttons for task graph, delegation run, delivery, and trace JSON panels.
- Added browser clipboard helper and toast feedback for copied artifacts.
- Added `/api/agent-studio/resume-run` so Save & Continue can resume the paused delegated run path instead of only saving a secret.
- Preserved `/` manual approval flow and `/agent-studio` auto-approval delegation mode.
- Runtime workspace is excluded from the source package; only `runtime/.gitkeep` is kept.


## V2.8.8 Durable Checkpoint Runtime

- Agent Studio resume now uses the same delegation run instead of starting a new run.
- Paused participant execution is resumed from the saved ai_core checkpoint.
- auxiliary_brain remains a coordinator only: it manages participants, tasks, runs, state, and delivery.
- ai_core owns participant execution, tool planning/execution, checkpoint continuation, and final synthesis.
- Save & Continue stores the secret, then calls resume-run; resume-run continues the blocked primary-runtime node instead of re-running completed participants.
- runtime workspace is intentionally excluded from the source package except runtime/.gitkeep.

## V2.8.9 Runtime Telemetry Bridge

- Primary runtime node events are mirrored into delegation run progress.
- Agent Studio can show whether the primary runtime is executing, waiting, failed, or completed at node level.
- Durable resume keeps the same delegation run and continues from checkpoint while preserving visible progress events.
- Runtime workspace is excluded from source packages; only `runtime/.gitkeep` is kept.

## V2.8.10 Delegation Objective Separation & Resume Result Merge

- Participant creation now stores both the original definition instruction and a runtime execution objective.
- Delegated execution sends only the participant work objective to ai_core, so ai_core does not confuse agent definition with task execution.
- Durable resume now replaces stale paused participant results with completed results.
- Final delegated synthesis filters out old waiting placeholders before generating the final answer.
- Runtime workspace remains source-clean; generated runtime content is not included in the source package.

## V2.8.11 Runtime Semantic Contract Engine

This version adds a domain-neutral semantic validation layer. The core runtime does not hard-code business field names or scenario-specific rules. Runtime-generated contracts may declare semantic types, source policies, and constraints under `runtime/generated/contracts/`. The core only executes generic validation steps:

- infer generic fact type from evidence shape and local context
- apply contract and generic constraints
- filter invalid facts before final synthesis
- synthesize only from verified facts by default
- keep runtime workspace clean in source packages

Generated runtime files are not included in the source archive.

## V2.8.12 Runtime Fact Usability and Production Package Cleanup

- Fixed semantic over-filtering that caused completed participant runs to return only a safe-conversion fallback.
- The normalizer now ignores extractor trace text and prefers structured runtime evidence when available.
- Coordinate-like values are no longer allowed to poison nearby unrelated numeric facts in the same evidence window.
- Added a generic runtime-native observation execution path that is only activated by runtime-generated source/capability contracts.
- Agent delegation prompts now ask the primary runtime to prefer runtime-native observations when a task can be satisfied from current runtime state.
- Final synthesis still uses verified facts only; no business/domain field names were added to ai_core.
- Production source package excludes `tests/`, `scripts/`, `__pycache__/`, and runtime-generated files.

## V2.8.13 Runtime Capability Routing Engine

- Added a generic capability source routing layer.
- Execution mode selection is driven by config/runtime contracts instead of hard-coded business logic.
- Runtime-native observation, structured-provider, and web-retrieval are separated as source modes.
- Runtime-native observation can satisfy current local runtime state without web retrieval when the contract/policy selects that mode.
- Web retrieval remains a fallback instead of the default for every request.
- Added `.gitignore` to prevent cache/runtime artifacts from entering source packages.
- Production package excludes `tests/`, `scripts/`, `__pycache__/`, `.pyc`, and runtime-generated files.


## V2.8.14 Multi-Model Cognitive Routing

This version adds a generic cognitive model topology. The runtime can route low-complexity nodes to a local base model and escalate high-complexity or low-quality nodes to stronger local/API models through LiteLLM-compatible provider configuration.

Key points:

- `input_parsing` and simple intent-style nodes can stay on the configured local base model.
- Complex planning, semantic grounding, evidence verification, stable synthesis, and artifact/code generation can use stronger routes.
- Routing is based on structural runtime signals: node id, prompt/schema size, generic required capabilities, prior failures, and feedback scores.
- No business-domain vocabulary is hardcoded into `ai_core`; generated runtime topology and feedback are stored under `runtime/generated/modeling/`.
- `tests/`, `scripts/`, `__pycache__/`, `*.pyc`, and runtime execution artifacts are excluded from the source package.

Important files:

```text
ai_core/runtime/modeling/
configs/model_routing_topology.json
ai_core/llm/provider_router.py
ai_core/llm/model_capability_matcher.py
```


## V2.8.15 Runtime Self-Governance Bootstrap

Goal: initialize a generic runtime governance graph at startup and use it to stabilize model selection, capability routing, MCP discovery, and feedback-based model escalation.

Implemented:
- Startup Runtime Bootstrap Service.
- Provider and model inventory discovery from runtime provider config.
- Strong-model topology generation when available, deterministic seed fallback otherwise.
- Runtime-generated governance graph under `runtime/generated/system_topology/`.
- Semantic capability taxonomy layer for generic source classification.
- Capability routing now respects semantic source category before fallback.
- Runtime-native execution no longer swallows external evidence steps.
- MCP registry preserved as a capability discovery source.
- Unknown capability discovery path added for future tool/model/MCP expansion.
- Feedback rejection records model escalation signals.
- Packaging excludes tests, scripts, caches, and runtime generated artifacts.
