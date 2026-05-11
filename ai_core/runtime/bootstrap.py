from ai_core.config.paths import (
    RUNTIME_DIR, RUNTIME_CONFIGS, RUNTIME_LOGS, RUNTIME_CHECKPOINTS,
    RUNTIME_TRACES, RUNTIME_KNOWLEDGE, RUNTIME_DATASETS, RUNTIME_GENERATED, RUNTIME_REGISTRY
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
            RUNTIME_GENERATED / "capabilities",
            RUNTIME_REGISTRY,
        ]:
            d.mkdir(parents=True, exist_ok=True)

        self._ensure_provider_config()
        self._ensure_auto_answers()
        self._ensure_command_profiles()
        self._ensure_model_route_config()
        self._ensure_capability_config()
        self._ensure_workflow_config()
        self._ensure_capability_routes()
        self._ensure_base_capability_templates()
        self._ensure_registry_files()
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


    def _ensure_capability_routes(self) -> None:
        p = RUNTIME_CONFIGS / "capabilities" / "capability_routes.yaml"
        if p.exists():
            return
        self.loader.save_yaml(p, {
            "default_route": ["local_model_service", "external_api_model"],
            "node_capability_map": {
                "input_parsing": ["local_model_service", "external_api_model"],
                "intent_recognition": ["local_model_service", "external_api_model"],
                "context_awareness": ["local_knowledge_store"],
                "workflow_planning": ["local_model_service", "external_api_model"],
                "execution": ["generic_tool_execution"],
                "feedback_learning": ["local_knowledge_store"],
                "output": ["local_model_service", "external_api_model"]
            },
            "policy": {
                "generate_missing_capability_spec": True,
                "human_review_generated_spec": True,
                "approval_required_for_install": True,
                "approval_required_for_start": True
            }
        })

    def _ensure_base_capability_templates(self) -> None:
        templates = {
            "local_model_service.yaml": {
                "capability_id": "local_model_service",
                "type": "model_service",
                "description": "A local LLM service. Candidate implementations can include Ollama, vLLM, LM Studio, or any generated local model service.",
                "selection_policy": {"strategy": "first_available_or_generate", "candidates": ["ollama_runtime", "vllm_runtime", "lmstudio_runtime"]},
                "security": {"approval_required": True, "risk_level": "medium"}
            },
            "external_api_model.yaml": {
                "capability_id": "external_api_model",
                "type": "external_api",
                "description": "External API model provider. Runtime can register OpenAI, Claude, Gemini, or another provider through config.",
                "detect": {"env_keys": ["OPENAI_API_KEY"]},
                "verify": {"env_keys": ["OPENAI_API_KEY"]},
                "runtime_register": {"provider_name": "external_api_model"},
                "security": {"approval_required": False, "risk_level": "medium"}
            },
            "local_knowledge_store.yaml": {
                "capability_id": "local_knowledge_store",
                "type": "knowledge_store",
                "description": "Local runtime knowledge directory and dataset files.",
                "detect": {"paths": {"all": ["runtime/knowledge"]}},
                "install": {"all": []},
                "verify": {"paths": {"all": ["runtime/knowledge"]}},
                "runtime_register": {"tool_name": "local_knowledge_store"},
                "security": {"approval_required": False, "risk_level": "low"}
            },
            "generic_tool_execution.yaml": {
                "capability_id": "generic_tool_execution",
                "type": "tool_execution",
                "description": "Generic tool execution capability. Specific tools are generated into runtime/generated/tools.",
                "detect": {"paths": {"all": ["runtime/generated/tools"]}},
                "install": {"all": []},
                "verify": {"paths": {"all": ["runtime/generated/tools"]}},
                "runtime_register": {"tool_name": "generic_tool_execution"},
                "security": {"approval_required": True, "risk_level": "high"}
            }
        }
        for name, data in templates.items():
            p = RUNTIME_CONFIGS / "capabilities" / name
            if not p.exists():
                self.loader.save_yaml(p, data)

    def _ensure_registry_files(self) -> None:
        for name in ["installed_capabilities.json", "provider_registry.json", "tool_registry.json"]:
            p = RUNTIME_REGISTRY / name
            if not p.exists():
                self.loader.save_json(p, {})

    def _ensure_dataset_files(self) -> None:
        for name in ["finetune.jsonl", "eval_cases.jsonl"]:
            p = RUNTIME_DATASETS / name
            if not p.exists():
                p.write_text("", encoding="utf-8")
