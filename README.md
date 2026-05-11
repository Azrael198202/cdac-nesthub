# Self-Bootstrap AI Core Console Stream

This version focuses on real workflow resume, provider self-healing, and visible console streaming.

## Key points

- `ai_core` contains no business logic.
- `runtime/` starts almost empty.
- Provider install/start/model pull are driven by runtime config.
- Human approval pauses the workflow.
- Approval resumes the same run from checkpoint.
- Long operations stream stdout/stderr to the UI.
- Chat input is fixed at the bottom.
- Message history scrolls independently.
- Execution workflow panel also streams events.

## Run

```bash
pip install -r requirements.txt
python main.py
```

Open:

```text
http://127.0.0.1:8000
```

## Important

Provider installation uses shell commands from:

```text
runtime/configs/environment/providers.yaml
```

The default config is generated on first run. Dangerous operations require approval.
