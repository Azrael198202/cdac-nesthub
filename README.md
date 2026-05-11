# cdac-nesthub

Config-driven AI Core scaffold with:
- `ai_core/` engine components (graph builder, node executor, config loader, validation, runtime evolution)
- `configs/` for workflows/prompts/models/capabilities/tools/security/memory/routing/agents
- `runtime/` generated/traces/logs/config artifacts
- `schema/` JSON schemas

## Run

```bash
python main.py
```

## Test

```bash
python -m unittest discover -s tests -p 'test_*.py'
```
