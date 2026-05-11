# Self-Bootstrapping AI Core

Config-driven AI runtime with environment self-healing.

Principles:

- `ai_core` has no business logic.
- `runtime/` starts empty and is generated while running.
- Provider/model/tool/environment rules are loaded from runtime configs.
- Missing provider/model can trigger human approval and automated install/verification.
- UI shows ChatGPT/Codex-like step streaming and human review checkpoints.

## Run

```bash
pip install -r requirements.txt
python main.py
```

Open:

```text
http://127.0.0.1:8000
```

## Smoke test

```bash
python scripts/smoke_test.py
```

## Important

The system can prepare install commands, but dangerous operations require human approval by default.
