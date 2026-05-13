from ai_core.config.paths import (
    RUNTIME_DIR, RUNTIME_CONFIGS, RUNTIME_CHECKPOINTS, RUNTIME_TRACES,
    RUNTIME_KNOWLEDGE, RUNTIME_DATASETS, RUNTIME_GENERATED, RUNTIME_REGISTRY
)
from ai_core.config.loader import ConfigLoader
from ai_core.runtime.runtime_template_generator import RuntimeTemplateGenerator


class RuntimeBootstrap:
    def __init__(self) -> None:
        self.loader = ConfigLoader()
        self.template_generator = RuntimeTemplateGenerator()

    def ensure(self) -> None:
        for d in [
            RUNTIME_DIR,
            RUNTIME_CONFIGS,
            RUNTIME_CONFIGS / "capabilities",
            RUNTIME_CONFIGS / "environment",
            RUNTIME_CONFIGS / "models",
            RUNTIME_CONFIGS / "secrets",
            RUNTIME_CONFIGS / "workflows",
            RUNTIME_CONFIGS / "policies",
            RUNTIME_CHECKPOINTS,
            RUNTIME_TRACES,
            RUNTIME_KNOWLEDGE,
            RUNTIME_DATASETS,
            RUNTIME_GENERATED / "capabilities",
            RUNTIME_GENERATED / "adapters",
            RUNTIME_GENERATED / "nodes",
            RUNTIME_GENERATED / "prompts",
            RUNTIME_GENERATED / "schemas",
            RUNTIME_GENERATED / "workflows",
            RUNTIME_GENERATED / "tools",
            RUNTIME_GENERATED / "policies",
            RUNTIME_GENERATED / "module_generation_requests",
            RUNTIME_GENERATED / "modules",
            RUNTIME_GENERATED / "api_discovery_requests",
            RUNTIME_GENERATED / "connectors",
            RUNTIME_REGISTRY,
            RUNTIME_TRACES / "api_discovery",
            RUNTIME_TRACES / "web_research",
        ]:
            d.mkdir(parents=True, exist_ok=True)

        self._ensure_model_providers()
        self._ensure_workflow()
        self._ensure_node_configs()
        self._ensure_runtime_templates()
        self._ensure_adapters()
        self._ensure_capability_routes()
        self._ensure_base_capabilities()
        self._ensure_environment()
        self._ensure_registry()
        self._ensure_datasets()

    def _ensure_model_providers(self) -> None:
        p = RUNTIME_CONFIGS / "models" / "providers.yaml"
        if p.exists():
            return
        self.loader.save_yaml(p, {
            "default_route": ["ollama", "openai"],
            "routes": {
                "code_generation": ["openai", "vllm", "lmstudio", "ollama"],
                "api_discovery_local": ["ollama"],
                "api_discovery_external": ["openai"],
                "reasoning": ["ollama", "openai"],
                "fallback": ["openai"]
            },
            "providers": {
                "ollama": {
                    "enabled": True,
                    "type": "ollama",
                    "base_url": "http://127.0.0.1:11434",
                    "binary": "ollama",
                    "auto_install": True,
                    "install": {
                        "windows": [
                            "winget install Ollama.Ollama --accept-source-agreements --accept-package-agreements --disable-interactivity"
                        ],
                        "macos": [
                            "brew install ollama"
                        ],
                        "linux": [
                            "curl -fsSL https://ollama.com/install.sh | sh"
                        ]
                    },
                    "executable_hints": {
                        "windows": [
                            "%LOCALAPPDATA%\\Programs\\Ollama\\ollama.exe",
                            "%ProgramFiles%\\Ollama\\ollama.exe"
                        ]
                    },
                    "endpoint_strategy": "auto",
                    "chat_endpoint": "/api/chat",
                    "generate_endpoint": "/api/generate",
                    "model": "qwen3:4b",
                    "fallback_models": ["qwen2.5:3b", "qwen3:1.7b", "llama3.2:3b"],
                    "timeout_seconds": 120,
                    "auto_start": True,
                    "start_command": "{binary} serve",
                    "ready_timeout_seconds": 30,
                    "ready_poll_interval_seconds": 1,
                    "auto_pull_missing_model": True,
                    "pull_command": "{binary} pull {model}",
                    "pull_timeout_seconds": 3600
                },
                "openai": {
                    "enabled": True,
                    "type": "openai",
                    "api_key_env": "OPENAI_API_KEY",
                    "model": "gpt-4o-mini",
                    "timeout_seconds": 120,
                    "interactive_key_required": True
                },
                "vllm": {
                    "enabled": False,
                    "type": "openai_compatible",
                    "base_url": "http://127.0.0.1:8001",
                    "endpoint": "/v1/chat/completions",
                    "model": "Qwen/Qwen2.5-7B-Instruct",
                    "timeout_seconds": 120,
                    "response_format_json": True
                },
                "lmstudio": {
                    "enabled": False,
                    "type": "openai_compatible",
                    "base_url": "http://127.0.0.1:1234",
                    "endpoint": "/v1/chat/completions",
                    "model": "local-model",
                    "timeout_seconds": 120,
                    "response_format_json": True
                }
            },
            "policy": {
                "require_real_provider": True,
                "allow_placeholder_result": False
            }
        })

    def _ensure_workflow(self) -> None:
        p = RUNTIME_CONFIGS / "workflows" / "base_orchestration.yaml"
        if p.exists():
            return
        self.loader.save_yaml(p, {
            "workflow_id": "base_orchestration",
            "name": "Base Config Driven Orchestration",
            "nodes": [
                {"id": "input_parsing", "node_config": "runtime/generated/nodes/input_parsing.yaml"},
                {"id": "intent_recognition", "node_config": "runtime/generated/nodes/intent_recognition.yaml"},
                {"id": "context_awareness", "node_config": "runtime/generated/nodes/context_awareness.yaml"},
                {"id": "workflow_planning", "node_config": "runtime/generated/nodes/workflow_planning.yaml"},
                {"id": "execution", "node_config": "runtime/generated/nodes/execution.yaml"},
                {"id": "feedback_learning", "node_config": "runtime/generated/nodes/feedback_learning.yaml"},
                {"id": "output", "node_config": "runtime/generated/nodes/output.yaml"}
            ]
        })

    def _ensure_node_configs(self) -> None:
        nodes = {
            "input_parsing": {
                "node_id": "input_parsing",
                "executor_type": "llm_json",
                "prompt": "runtime/generated/prompts/input_parsing.yaml",
                "output_schema": "runtime/generated/schemas/input_parsing.schema.json",
                "adapter": "runtime/generated/adapters/input_parsing.yaml",
                "capabilities": ["text_understanding"],
                "review_required": True,
                "progress_weight": 15
            },
            "intent_recognition": {
                "node_id": "intent_recognition",
                "executor_type": "llm_json",
                "prompt": "runtime/generated/prompts/intent_recognition.yaml",
                "output_schema": "runtime/generated/schemas/intent_recognition.schema.json",
                "adapter": "runtime/generated/adapters/intent_recognition.yaml",
                "capabilities": ["text_understanding"],
                "review_required": True,
                "progress_weight": 15
            },
            "context_awareness": {
                "node_id": "context_awareness",
                "executor_type": "static_transform",
                "prompt": "runtime/generated/prompts/context_awareness.yaml",
                "output_schema": "runtime/generated/schemas/context_awareness.schema.json",
                "capabilities": ["local_knowledge_store"],
                "review_required": False,
                "progress_weight": 10
            },
            "workflow_planning": {
                "node_id": "workflow_planning",
                "executor_type": "llm_json",
                "prompt": "runtime/generated/prompts/workflow_planning.yaml",
                "output_schema": "runtime/generated/schemas/workflow_planning.schema.json",
                "adapter": "runtime/generated/adapters/workflow_planning.yaml",
                "capabilities": ["workflow_generation"],
                "review_required": True,
                "progress_weight": 20
            },
            "execution": {
                "node_id": "execution",
                "executor_type": "tool_call",
                "prompt": "runtime/generated/prompts/execution.yaml",
                "output_schema": "runtime/generated/schemas/execution.schema.json",
                "capabilities": ["generic_tool_execution"],
                "review_required": True,
                "progress_weight": 25
            },
            "feedback_learning": {
                "node_id": "feedback_learning",
                "executor_type": "static_transform",
                "prompt": "runtime/generated/prompts/feedback_learning.yaml",
                "output_schema": "runtime/generated/schemas/feedback_learning.schema.json",
                "capabilities": ["local_knowledge_store"],
                "review_required": False,
                "progress_weight": 10
            },
            "output": {
                "node_id": "output",
                "executor_type": "output",
                "prompt": "runtime/generated/prompts/output.yaml",
                "output_schema": "runtime/generated/schemas/output.schema.json",
                "capabilities": ["response_generation"],
                "review_required": False,
                "progress_weight": 5
            }
        }
        for node_id, cfg in nodes.items():
            p = RUNTIME_GENERATED / "nodes" / f"{node_id}.yaml"
            if not p.exists():
                self.loader.save_yaml(p, cfg)


    def _ensure_runtime_templates(self) -> None:
        node_executor_types = {
            "input_parsing": "llm_json",
            "intent_recognition": "llm_json",
            "context_awareness": "static_transform",
            "workflow_planning": "llm_json",
            "execution": "tool_call",
            "feedback_learning": "static_transform",
            "output": "output",
        }
        for node_id, executor_type in node_executor_types.items():
            self.template_generator.ensure_node_template(node_id, executor_type)

    def _ensure_prompts(self) -> None:
        prompts = {
            "input_parsing": {
                "id": "input_parsing_prompt",
                "version": "1.0",
                "executor_type": "llm_json",
                "system": "You are a generic input parsing engine. Return JSON only according to the output schema. Do not execute tools.",
                "user_template": "User input: {{ user_input }}\nPrevious results: {{ previous_results }}\nCorrection memory: {{ correction_memory }}",
                "output_contract": {
                    "language": "string",
                    "intent_type": "string",
                    "tasks": "array",
                    "missing_information": "array",
                    "required_capabilities": "array",
                    "safety_notes": "array",
                    "original_input": "string"
                }
            },
            "intent_recognition": {
                "id": "intent_recognition_prompt",
                "version": "1.0",
                "executor_type": "llm_json",
                "system": "You are a generic intent recognition engine. Use previous node results and return JSON only.",
                "user_template": "User input: {{ user_input }}\nPrevious results: {{ previous_results }}\nCorrection memory: {{ correction_memory }}",
                "output_contract": {
                    "intent_type": "string",
                    "confidence": "number",
                    "tasks": "array",
                    "requires_human_review": "boolean",
                    "reason": "string"
                }
            },
            "workflow_planning": {
                "id": "workflow_planning_prompt",
                "version": "1.0",
                "executor_type": "llm_json",
                "system": "You are a generic workflow planner. Produce a plan from previous structured results. Return JSON only.",
                "user_template": "User input: {{ user_input }}\nPrevious results: {{ previous_results }}\nCorrection memory: {{ correction_memory }}",
                "output_contract": {
                    "planned_steps": "array",
                    "blocking_missing_information": "array",
                    "required_capabilities": "array"
                }
            },
            "context_awareness": {"id": "context_awareness_prompt", "version": "1.0", "executor_type": "static_transform"},
            "execution": {"id": "execution_prompt", "version": "1.0", "executor_type": "tool_call"},
            "feedback_learning": {"id": "feedback_learning_prompt", "version": "1.0", "executor_type": "static_transform"},
            "output": {"id": "output_prompt", "version": "1.0", "executor_type": "output"}
        }
        for name, cfg in prompts.items():
            p = RUNTIME_GENERATED / "prompts" / f"{name}.yaml"
            if not p.exists():
                self.loader.save_yaml(p, cfg)

    def _ensure_schemas(self) -> None:
        schemas = {
            "input_parsing": {
                "type": "object",
                "required": ["language", "intent_type", "tasks", "missing_information", "required_capabilities", "original_input"],
                "properties": {
                    "language": {"type": "string"},
                    "intent_type": {"type": "string"},
                    "tasks": {"type": "array"},
                    "missing_information": {"type": "array"},
                    "required_capabilities": {"type": "array"},
                    "safety_notes": {"type": "array"},
                    "original_input": {"type": "string"}
                }
            },
            "intent_recognition": {
                "type": "object",
                "required": ["intent_type", "confidence", "tasks"],
                "properties": {
                    "intent_type": {"type": "string"},
                    "confidence": {"type": "number"},
                    "tasks": {"type": "array"},
                    "requires_human_review": {"type": "boolean"},
                    "reason": {"type": "string"}
                }
            },
            "workflow_planning": {
                "type": "object",
                "required": ["planned_steps"],
                "properties": {
                    "planned_steps": {"type": "array"},
                    "blocking_missing_information": {"type": "array"},
                    "required_capabilities": {"type": "array"}
                }
            },
            "context_awareness": {"type": "object"},
            "execution": {"type": "object"},
            "feedback_learning": {"type": "object"},
            "output": {"type": "object"}
        }
        for name, schema in schemas.items():
            p = RUNTIME_GENERATED / "schemas" / f"{name}.schema.json"
            if not p.exists():
                self.loader.save_json(p, schema)

    def _ensure_adapters(self) -> None:
        adapters = {
            "input_parsing": {
                "adapter_id": "input_parsing_adapter",
                "type": "llm_json",
                "provider_route": ["ollama", "openai"],
                "prompt": "runtime/generated/prompts/input_parsing.yaml",
                "output_schema": "runtime/generated/schemas/input_parsing.schema.json",
                "json_mode": True
            },
            "intent_recognition": {
                "adapter_id": "intent_recognition_adapter",
                "type": "llm_json",
                "provider_route": ["ollama", "openai"],
                "prompt": "runtime/generated/prompts/intent_recognition.yaml",
                "output_schema": "runtime/generated/schemas/intent_recognition.schema.json",
                "json_mode": True
            },
            "workflow_planning": {
                "adapter_id": "workflow_planning_adapter",
                "type": "llm_json",
                "provider_route": ["ollama", "openai"],
                "prompt": "runtime/generated/prompts/workflow_planning.yaml",
                "output_schema": "runtime/generated/schemas/workflow_planning.schema.json",
                "json_mode": True
            }
        }
        for name, cfg in adapters.items():
            p = RUNTIME_GENERATED / "adapters" / f"{name}.yaml"
            if not p.exists():
                self.loader.save_yaml(p, cfg)

    def _ensure_capability_routes(self) -> None:
        p = RUNTIME_CONFIGS / "capabilities" / "capability_routes.yaml"
        if p.exists():
            return
        self.loader.save_yaml(p, {"policy": {"generate_missing_capability_spec": True, "human_review_generated_spec": True}})

    def _ensure_base_capabilities(self) -> None:
        specs = {
            "text_understanding": "Generic text understanding capability.",
            "workflow_generation": "Generic workflow generation capability.",
            "local_knowledge_store": "Local knowledge storage capability.",
            "generic_tool_execution": "Generic runtime tool execution capability.",
            "response_generation": "Generic response generation capability."
        }
        for cap_id, desc in specs.items():
            p = RUNTIME_CONFIGS / "capabilities" / f"{cap_id}.yaml"
            if not p.exists():
                self.loader.save_yaml(p, {
                    "capability_id": cap_id,
                    "type": "generic_capability",
                    "description": desc,
                    "detect": {"binary": [], "paths": {"all": []}, "env_keys": []},
                    "install": {"all": []},
                    "verify": {"commands": {"all": []}, "paths": {"all": []}, "health_urls": []},
                    "runtime_register": {"tool_name": cap_id},
                    "security": {"approval_required": False, "risk_level": "low"}
                })

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
