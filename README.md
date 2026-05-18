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
