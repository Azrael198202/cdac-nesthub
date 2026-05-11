from __future__ import annotations

from ai_core.config.paths import ensure_runtime_dirs, RUNTIME_CONFIGS_DIR, RUNTIME_DATASETS_DIR
from ai_core.config.loader import ConfigLoader


class RuntimeBootstrap:
    """Create only generic runtime config. No business logic belongs here."""

    def __init__(self):
        self.loader = ConfigLoader()

    def ensure(self) -> None:
        ensure_runtime_dirs()
        self._ensure_environment_config()
        self._ensure_model_routes()
        self._ensure_base_workflow()
        self._ensure_dataset_files()

    def _ensure_environment_config(self) -> None:
        path = RUNTIME_CONFIGS_DIR / "environment" / "providers.yaml"
        if path.exists():
            return
        self.loader.write(path, {
            "defaults": {
                "approval_required_for_install": True,
                "auto_install_enabled": True,
                "auto_start_enabled": True,
                "command_timeout_seconds": 1800,
            },
            "providers": {
                "ollama": {
                    "enabled": True,
                    "kind": "local_llm_server",
                    "base_url": "http://127.0.0.1:11434",
                    "health_url": "http://127.0.0.1:11434/api/tags",
                    "binary": "ollama",
                    "models": ["qwen3:4b"],
                    "install": {
                        "linux": ["curl -fsSL https://ollama.com/install.sh | sh"],
                        "mac": ["brew install ollama"],
                        "windows": ["winget install Ollama.Ollama"],
                    },
                    "start": {
                        "linux": ["nohup ollama serve > runtime/logs/ollama.log 2>&1 &"],
                        "mac": ["nohup ollama serve > runtime/logs/ollama.log 2>&1 &"],
                        "windows": ["ollama serve"],
                    },
                    "model_install": ["ollama pull {model}"],
                },
                "openai": {
                    "enabled": True,
                    "kind": "external_llm_api",
                    "requires_key": True,
                    "env_keys": ["OPENAI_API_KEY"],
                    "base_url": "https://api.openai.com/v1",
                    "model": "gpt-4o-mini",
                },
                "huggingface": {
                    "enabled": True,
                    "kind": "model_repository",
                    "requires_key": False,
                    "note": "Search/download logic can be plugged in through runtime generated adapters.",
                },
            },
        })

    def _ensure_model_routes(self) -> None:
        path = RUNTIME_CONFIGS_DIR / "models" / "routes.yaml"
        if path.exists():
            return
        self.loader.write(path, {
            "default_route": ["ollama", "huggingface", "openai"],
            "tasks": {
                "input_parsing": ["ollama", "openai"],
                "intent_recognition": ["ollama", "openai"],
                "workflow_planning": ["ollama", "openai"],
                "execution_review": ["ollama", "openai"],
            },
        })

    def _ensure_base_workflow(self) -> None:
        path = RUNTIME_CONFIGS_DIR / "workflows" / "base_orchestration.yaml"
        if path.exists():
            return
        self.loader.write(path, {
            "workflow_id": "base_orchestration",
            "description": "Generic orchestration. Business-specific workflow is generated in runtime after intent planning.",
            "nodes": [
                {"id": "input_parsing", "type": "llm_step", "review_required": True},
                {"id": "intent_recognition", "type": "llm_step", "review_required": True},
                {"id": "context_awareness", "type": "memory_step", "review_required": False},
                {"id": "workflow_planning", "type": "llm_step", "review_required": True},
                {"id": "execution", "type": "dynamic_execution", "review_required": True},
                {"id": "feedback_learning", "type": "learning_step", "review_required": False},
                {"id": "output", "type": "output_step", "review_required": False},
            ],
        })

    def _ensure_dataset_files(self) -> None:
        for name in ["finetune.jsonl", "eval_cases.jsonl"]:
            path = RUNTIME_DATASETS_DIR / name
            if not path.exists():
                path.write_text("", encoding="utf-8")
