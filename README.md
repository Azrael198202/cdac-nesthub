# Pure Runtime AI Core with Visible Workflow UI

This project keeps `ai_core` free from business/domain logic. The core is only an execution engine.
Runtime configuration is generated under `runtime/` when the app runs.

## Principles

- `ai_core` contains only generic orchestration, model routing, validation, runtime config loading, event streaming, and trace writing.
- No domain-specific workflows, tools, or examples are embedded in `ai_core`.
- `runtime/` starts empty except for `.gitkeep`.
- Runtime files are generated only after user interaction or API calls.
- No fake tool result is returned. If no real local or external LLM is available, the system asks for configuration instead of pretending.
- The web app shows the execution process like a ChatGPT/Codex style task console.

## Start

```bash
pip install -r requirements.txt
python main.py
```

Open:

```text
http://127.0.0.1:8000
```

## Optional LLM setup

Use one of the following:

```bash
export OPENAI_API_KEY=your_key
export AI_CORE_PROVIDER=openai
```

or run Ollama locally:

```bash
ollama serve
ollama pull qwen3:4b
export AI_CORE_PROVIDER=ollama
export AI_CORE_OLLAMA_MODEL=qwen3:4b
```

You can also configure the provider from the web page. The API key is written to `runtime/secrets/local.env`, which is ignored by Git.
