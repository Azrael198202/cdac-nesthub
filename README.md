# Verified Self-Evolving AI Core

Config/runtime-driven AI Core. `ai_core` is stable engine code. `runtime/` starts almost empty and is generated during execution.

## Run

```bash
pip install -r requirements.txt
python main.py
```

Open http://127.0.0.1:8000

## Demo

```bash
python main.py --demo
python scripts/smoke_test.py
```

Demo input:

```text
Please check the weather forecast for Tokyo tomorrow and then book a flight to Tokyo.
```

The system runs:

Input Parsing → Intent Recognition → Context Awareness → Workflow Planning → Execution → Feedback Learning → Output

Each step uses:

Knowledge lookup → local model → self validation → human review → external API reviewer fallback → config generation/update → retry → save learning data

## External API key

At runtime, add an external API key in the web UI settings or CLI:

```bash
python scripts/set_api_key.py --provider openai --key sk-xxxx
```

Keys are saved to `runtime/secrets/local_secrets.json` for local development only.
