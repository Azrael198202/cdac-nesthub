import platform
import yaml
from pathlib import Path
from ai_core.config.paths import RUNTIME_DIR, RUNTIME_CONFIGS, RUNTIME_LOGS, RUNTIME_CHECKPOINTS, RUNTIME_TRACES


class RuntimeBootstrap:
    def ensure(self) -> None:
        for d in [
            RUNTIME_DIR,
            RUNTIME_CONFIGS,
            RUNTIME_CONFIGS / "environment",
            RUNTIME_CONFIGS / "workflows",
            RUNTIME_CONFIGS / "models",
            RUNTIME_CONFIGS / "prompts",
            RUNTIME_CONFIGS / "tools",
            RUNTIME_LOGS,
            RUNTIME_CHECKPOINTS,
            RUNTIME_TRACES,
        ]:
            d.mkdir(parents=True, exist_ok=True)

        self._ensure_provider_config()
        self._ensure_workflow_config()

    def _ensure_provider_config(self) -> None:
        p = RUNTIME_CONFIGS / "environment" / "providers.yaml"
        if p.exists():
            return

        system = platform.system().lower()
        data = {
            "providers": {
                "ollama": {
                    "enabled": True,
                    "priority": 10,
                    "requires_approval": True,
                    "binary": "ollama",
                    "host": "http://127.0.0.1:11434",
                    "health_url": "http://127.0.0.1:11434/api/tags",
                    "default_model": "qwen3:4b",
                    "install": {
                        "windows": ["winget install Ollama.Ollama"],
                        "darwin": ["brew install ollama"],
                        "linux": ["curl -fsSL https://ollama.com/install.sh | sh"],
                    },
                    "start": {
                        "windows": ["ollama serve"],
                        "darwin": ["ollama serve"],
                        "linux": ["ollama serve"],
                    },
                    "pull_model": ["ollama pull {model}"],
                },
                "openai": {
                    "enabled": True,
                    "priority": 100,
                    "requires_key": True,
                    "env_key": "OPENAI_API_KEY",
                    "default_model": "gpt-4.1-mini",
                },
            }
        }
        p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")

    def _ensure_workflow_config(self) -> None:
        p = RUNTIME_CONFIGS / "workflows" / "base_orchestration.yaml"
        if p.exists():
            return

        data = {
            "workflow_id": "base_orchestration",
            "name": "Base Configurable Orchestration",
            "nodes": [
                {"id": "input_parsing", "type": "llm_json", "review_required": True},
                {"id": "intent_recognition", "type": "llm_json", "review_required": True},
                {"id": "context_awareness", "type": "knowledge_lookup", "review_required": False},
                {"id": "workflow_planning", "type": "llm_json", "review_required": True},
                {"id": "execution", "type": "tool_or_agent_execution", "review_required": True},
                {"id": "feedback_learning", "type": "learning", "review_required": False},
                {"id": "output", "type": "output", "review_required": False},
            ],
        }
        p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
