from ai_core.config.paths import (
    RUNTIME_DIR, RUNTIME_CONFIGS, RUNTIME_CHECKPOINTS, RUNTIME_TRACES,
    RUNTIME_KNOWLEDGE, RUNTIME_DATASETS, RUNTIME_GENERATED, RUNTIME_REGISTRY
)
from ai_core.config.loader import ConfigLoader


class RuntimeBootstrap:
    def __init__(self) -> None:
        self.loader = ConfigLoader()

    def ensure(self) -> None:
        for d in [
            RUNTIME_DIR,
            RUNTIME_CONFIGS,
            RUNTIME_CONFIGS / "capabilities",
            RUNTIME_CONFIGS / "environment",
            RUNTIME_CONFIGS / "workflows",
            RUNTIME_CHECKPOINTS,
            RUNTIME_TRACES,
            RUNTIME_KNOWLEDGE,
            RUNTIME_DATASETS,
            RUNTIME_GENERATED / "capabilities",
            RUNTIME_REGISTRY,
        ]:
            d.mkdir(parents=True, exist_ok=True)

        self._ensure_workflow()
        self._ensure_capability_routes()
        self._ensure_base_capabilities()
        self._ensure_environment()
        self._ensure_registry()
        self._ensure_datasets()

    def _ensure_workflow(self) -> None:
        p = RUNTIME_CONFIGS / "workflows" / "base_orchestration.yaml"
        if p.exists():
            return
        self.loader.save_yaml(p, {
            "workflow_id": "base_orchestration",
            "name": "Base Dynamic Capability Orchestration",
            "nodes": [
                {"id": "input_parsing", "type": "input_parsing", "review_required": True, "progress_weight": 15},
                {"id": "intent_recognition", "type": "intent_recognition", "review_required": True, "progress_weight": 15},
                {"id": "context_awareness", "type": "context_awareness", "review_required": False, "progress_weight": 10},
                {"id": "workflow_planning", "type": "workflow_planning", "review_required": True, "progress_weight": 20},
                {"id": "execution", "type": "execution", "review_required": True, "progress_weight": 25},
                {"id": "feedback_learning", "type": "feedback_learning", "review_required": False, "progress_weight": 10},
                {"id": "output", "type": "output", "review_required": False, "progress_weight": 5}
            ]
        })

    def _ensure_capability_routes(self) -> None:
        p = RUNTIME_CONFIGS / "capabilities" / "capability_routes.yaml"
        if p.exists():
            return
        self.loader.save_yaml(p, {
            "node_capability_map": {
                "input_parsing": ["text_understanding"],
                "intent_recognition": ["text_understanding"],
                "context_awareness": ["local_knowledge_store"],
                "workflow_planning": ["workflow_generation"],
                "execution": ["generic_tool_execution"],
                "feedback_learning": ["local_knowledge_store"],
                "output": ["response_generation"]
            },
            "policy": {
                "generate_missing_capability_spec": True,
                "human_review_generated_spec": True,
                "approval_required_for_install": True
            }
        })

    def _ensure_base_capabilities(self) -> None:
        specs = {
            "text_understanding.yaml": {
                "capability_id": "text_understanding",
                "type": "reasoning_capability",
                "description": "Generic language understanding capability.",
                "detect": {"paths": {"all": []}, "binary": [], "env_keys": []},
                "install": {"all": []},
                "verify": {"paths": {"all": []}, "commands": {"all": []}, "health_urls": []},
                "runtime_register": {"tool_name": "text_understanding"},
                "security": {"approval_required": False, "risk_level": "low"}
            },
            "workflow_generation.yaml": {
                "capability_id": "workflow_generation",
                "type": "planning_capability",
                "description": "Generic workflow planning capability.",
                "detect": {"paths": {"all": []}, "binary": [], "env_keys": []},
                "install": {"all": []},
                "verify": {"paths": {"all": []}, "commands": {"all": []}, "health_urls": []},
                "runtime_register": {"tool_name": "workflow_generation"},
                "security": {"approval_required": False, "risk_level": "low"}
            },
            "local_knowledge_store.yaml": {
                "capability_id": "local_knowledge_store",
                "type": "knowledge_store",
                "description": "Local runtime knowledge directory.",
                "detect": {"paths": {"all": ["runtime/knowledge"]}, "binary": [], "env_keys": []},
                "install": {"all": []},
                "verify": {"paths": {"all": ["runtime/knowledge"]}, "commands": {"all": []}, "health_urls": []},
                "runtime_register": {"tool_name": "local_knowledge_store"},
                "security": {"approval_required": False, "risk_level": "low"}
            },
            "generic_tool_execution.yaml": {
                "capability_id": "generic_tool_execution",
                "type": "tool_execution",
                "description": "Generic runtime tool execution capability.",
                "detect": {"paths": {"all": ["runtime/generated"]}, "binary": [], "env_keys": []},
                "install": {"all": []},
                "verify": {"paths": {"all": ["runtime/generated"]}, "commands": {"all": []}, "health_urls": []},
                "runtime_register": {"tool_name": "generic_tool_execution"},
                "security": {"approval_required": True, "risk_level": "medium"}
            },
            "response_generation.yaml": {
                "capability_id": "response_generation",
                "type": "response_capability",
                "description": "Generic response generation capability.",
                "detect": {"paths": {"all": []}, "binary": [], "env_keys": []},
                "install": {"all": []},
                "verify": {"paths": {"all": []}, "commands": {"all": []}, "health_urls": []},
                "runtime_register": {"tool_name": "response_generation"},
                "security": {"approval_required": False, "risk_level": "low"}
            }
        }
        for name, spec in specs.items():
            p = RUNTIME_CONFIGS / "capabilities" / name
            if not p.exists():
                self.loader.save_yaml(p, spec)

    def _ensure_environment(self) -> None:
        auto = RUNTIME_CONFIGS / "environment" / "auto_answers.yaml"
        if not auto.exists():
            self.loader.save_yaml(auto, {"enabled": True, "rules": [{"match": "Do you agree", "answer": "Y"}]})
        profiles = RUNTIME_CONFIGS / "environment" / "command_profiles.yaml"
        if not profiles.exists():
            self.loader.save_yaml(profiles, {
                "default": {"timeout_seconds": 1200, "retries": 1, "use_pty": False, "auto_answer": True},
                "profiles": [
                    {"name": "winget", "match_prefix": "winget", "append_args": ["--accept-source-agreements", "--accept-package-agreements", "--disable-interactivity"], "retries": 2, "timeout_seconds": 3600}
                ]
            })

    def _ensure_registry(self) -> None:
        for name in ["installed_capabilities.json", "tool_registry.json", "provider_registry.json"]:
            p = RUNTIME_REGISTRY / name
            if not p.exists():
                self.loader.save_json(p, {})

    def _ensure_datasets(self) -> None:
        for name in ["finetune.jsonl", "eval_cases.jsonl"]:
            p = RUNTIME_DATASETS / name
            if not p.exists():
                p.write_text("", encoding="utf-8")
