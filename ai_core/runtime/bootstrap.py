from ai_core.config.paths import (
    RUNTIME_DIR, RUNTIME_CONFIGS, RUNTIME_LOGS, RUNTIME_CHECKPOINTS,
    RUNTIME_TRACES, RUNTIME_KNOWLEDGE, RUNTIME_DATASETS, RUNTIME_GENERATED
)
from ai_core.config.loader import ConfigLoader


class RuntimeBootstrap:
    def __init__(self) -> None:
        self.loader = ConfigLoader()

    def ensure(self) -> None:
        for d in [
            RUNTIME_DIR,
            RUNTIME_CONFIGS,
            RUNTIME_CONFIGS / "environment",
            RUNTIME_CONFIGS / "workflows",
            RUNTIME_CONFIGS / "models",
            RUNTIME_CONFIGS / "prompts",
            RUNTIME_CONFIGS / "tools",
            RUNTIME_CONFIGS / "capabilities",
            RUNTIME_LOGS,
            RUNTIME_CHECKPOINTS,
            RUNTIME_TRACES,
            RUNTIME_KNOWLEDGE,
            RUNTIME_DATASETS,
            RUNTIME_GENERATED,
            RUNTIME_GENERATED / "tools",
            RUNTIME_GENERATED / "workflows",
            RUNTIME_GENERATED / "prompts",
            RUNTIME_GENERATED / "schemas",
        ]:
            d.mkdir(parents=True, exist_ok=True)

        self._ensure_provider_config()
        self._ensure_auto_answers()
        self._ensure_command_profiles()
        self._ensure_model_route_config()
        self._ensure_capability_config()
        self._ensure_workflow_config()
        self._ensure_dataset_files()

    def _ensure_provider_config(self) -> None:
        p = RUNTIME_CONFIGS / "environment" / "providers.yaml"
        if p.exists():
            return
        data = {
            "providers": {
                "ollama": {
                    "enabled": True,
                    "priority": 10,
                    "type": "local",
                    "requires_approval": True,
                    "binary": "ollama",
                    "host": "http://127.0.0.1:11434",
                    "health_url": "http://127.0.0.1:11434/api/tags",
                    "default_model": "qwen3:4b",
                    "install": {
                        "windows": ["winget install Ollama.Ollama"],
                        "darwin": ["brew install ollama"],
                        "linux": ["curl -fsSL https://ollama.com/install.sh | sh"]
                    },
                    "start": {
                        "windows": ["ollama serve"],
                        "darwin": ["ollama serve"],
                        "linux": ["ollama serve"]
                    },
                    "pull_model": ["ollama pull {model}"]
                },
                "huggingface": {
                    "enabled": True,
                    "priority": 50,
                    "type": "model_hub",
                    "requires_key": False,
                    "note": "Search/download logic can be extended by runtime-generated tools."
                },
                "openai": {
                    "enabled": True,
                    "priority": 100,
                    "type": "external_api",
                    "requires_key": True,
                    "env_key": "OPENAI_API_KEY",
                    "default_model": "gpt-4.1-mini"
                }
            }
        }
        self.loader.save_yaml(p, data)

    def _ensure_auto_answers(self) -> None:
        p = RUNTIME_CONFIGS / "environment" / "auto_answers.yaml"
        if p.exists():
            return
        data = {
            "enabled": True,
            "rules": [
                {"match": "Do you agree", "answer": "Y"},
                {"match": "agree to all", "answer": "Y"},
                {"match": "source agreements", "answer": "Y"},
                {"match": "terms of transaction", "answer": "Y"},
                {"match": "[Y/n]", "answer": "Y"},
                {"match": "[y/N]", "answer": "Y"},
                {"match": "Continue?", "answer": "Y"},
                {"match": "Proceed?", "answer": "Y"},
                {"match": "Press ENTER", "answer": ""},
                {"match": "license", "answer": "Y"},
                {"match": "confirmation", "answer": "Y"}
            ]
        }
        self.loader.save_yaml(p, data)

    def _ensure_command_profiles(self) -> None:
        p = RUNTIME_CONFIGS / "environment" / "command_profiles.yaml"
        if p.exists():
            return
        data = {
            "default": {
                "timeout_seconds": 1200,
                "retries": 1,
                "use_pty": False,
                "auto_answer": True
            },
            "profiles": [
                {
                    "name": "winget",
                    "match_prefix": "winget",
                    "use_pty": False,
                    "timeout_seconds": 1800,
                    "retries": 1,
                    "append_args": [
                        "--accept-source-agreements",
                        "--accept-package-agreements"
                    ],
                    "recovery_commands": [
                        "winget source update"
                    ]
                },
                {
                    "name": "apt",
                    "match_prefix": "apt",
                    "use_pty": True,
                    "timeout_seconds": 1800,
                    "retries": 1,
                    "prepend_env": {"DEBIAN_FRONTEND": "noninteractive"},
                    "append_args": ["-y"]
                },
                {
                    "name": "dnf",
                    "match_prefix": "dnf",
                    "use_pty": True,
                    "timeout_seconds": 1800,
                    "retries": 1,
                    "append_args": ["-y"]
                },
                {
                    "name": "brew",
                    "match_prefix": "brew",
                    "use_pty": True,
                    "timeout_seconds": 1800,
                    "retries": 1
                },
                {
                    "name": "pip",
                    "match_contains": "pip install",
                    "use_pty": False,
                    "timeout_seconds": 1800,
                    "retries": 2,
                    "append_args": ["--disable-pip-version-check"]
                },
                {
                    "name": "npm",
                    "match_prefix": "npm",
                    "use_pty": False,
                    "timeout_seconds": 1800,
                    "retries": 1
                },
                {
                    "name": "playwright",
                    "match_contains": "playwright install",
                    "use_pty": False,
                    "timeout_seconds": 1800,
                    "retries": 1
                },
                {
                    "name": "ollama",
                    "match_prefix": "ollama",
                    "use_pty": True,
                    "timeout_seconds": 3600,
                    "retries": 1
                }
            ]
        }
        self.loader.save_yaml(p, data)

    def _ensure_model_route_config(self) -> None:
        p = RUNTIME_CONFIGS / "models" / "model_routes.yaml"
        if p.exists():
            return
        data = {
            "default_route": ["ollama", "huggingface", "openai"],
            "task_routes": {
                "input_parsing": ["ollama", "openai"],
                "intent_recognition": ["ollama", "openai"],
                "context_awareness": ["ollama", "openai"],
                "workflow_planning": ["ollama", "openai"],
                "execution": ["ollama", "openai"],
                "feedback_learning": ["ollama", "openai"],
                "output": ["ollama", "openai"]
            },
            "policy": {
                "local_first": True,
                "external_api_as_insurance": True,
                "human_approval_for_install": True,
                "human_approval_for_external_api": False
            }
        }
        self.loader.save_yaml(p, data)

    def _ensure_capability_config(self) -> None:
        p = RUNTIME_CONFIGS / "capabilities" / "task_capability_map.yaml"
        if p.exists():
            return
        data = {
            "input_parsing": ["text_understanding", "json_output"],
            "intent_recognition": ["classification", "entity_extraction", "json_output"],
            "context_awareness": ["memory_lookup", "knowledge_lookup"],
            "workflow_planning": ["task_decomposition", "workflow_generation", "json_output"],
            "execution": ["tool_calling", "agent_execution"],
            "feedback_learning": ["evaluation", "knowledge_write", "finetune_dataset_write"],
            "output": ["response_generation"]
        }
        self.loader.save_yaml(p, data)

    def _ensure_workflow_config(self) -> None:
        p = RUNTIME_CONFIGS / "workflows" / "base_orchestration.yaml"
        if p.exists():
            return
        data = {
            "workflow_id": "base_orchestration",
            "name": "Base Config Driven Orchestration",
            "nodes": [
                {"id": "input_parsing", "type": "llm_json", "review_required": True, "progress_weight": 15},
                {"id": "intent_recognition", "type": "llm_json", "review_required": True, "progress_weight": 15},
                {"id": "context_awareness", "type": "knowledge_lookup", "review_required": False, "progress_weight": 10},
                {"id": "workflow_planning", "type": "llm_json", "review_required": True, "progress_weight": 20},
                {"id": "execution", "type": "tool_or_agent_execution", "review_required": True, "progress_weight": 25},
                {"id": "feedback_learning", "type": "learning", "review_required": False, "progress_weight": 10},
                {"id": "output", "type": "output", "review_required": False, "progress_weight": 5}
            ]
        }
        self.loader.save_yaml(p, data)

    def _ensure_dataset_files(self) -> None:
        for name in ["finetune.jsonl", "eval_cases.jsonl"]:
            p = RUNTIME_DATASETS / name
            if not p.exists():
                p.write_text("", encoding="utf-8")
