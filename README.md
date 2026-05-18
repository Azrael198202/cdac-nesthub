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
