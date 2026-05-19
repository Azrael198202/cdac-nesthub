from pathlib import Path

from ai_core.config.paths import (
    RUNTIME_DIR, RUNTIME_CONFIGS, RUNTIME_CHECKPOINTS, RUNTIME_TRACES,
    RUNTIME_KNOWLEDGE, RUNTIME_DATASETS, RUNTIME_GENERATED, RUNTIME_REGISTRY
)
from ai_core.config.loader import ConfigLoader
from ai_core.runtime.runtime_template_generator import RuntimeTemplateGenerator
from ai_core.runtime.modeling.capability_topology import RuntimeModelTopology
from ai_core.runtime.modeling.model_stage_policy import ModelStagePolicy
from ai_core.runtime.modeling.runtime_execution_policy import RuntimeExecutionPolicy


class RuntimeBootstrap:
    def __init__(self) -> None:
        self.loader = ConfigLoader()
        self.template_generator = RuntimeTemplateGenerator()
        self.model_topology = RuntimeModelTopology()
        self.model_stage_policy = ModelStagePolicy()
        self.runtime_execution_policy = RuntimeExecutionPolicy()

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
            RUNTIME_GENERATED / "models",
            RUNTIME_GENERATED / "modeling",
            RUNTIME_GENERATED / "providers",
            RUNTIME_GENERATED / "system_topology",
            RUNTIME_GENERATED / "api_discovery_requests",
            RUNTIME_GENERATED / "connectors",
            RUNTIME_REGISTRY,
            RUNTIME_TRACES / "api_discovery",
            RUNTIME_TRACES / "web_research",
            RUNTIME_TRACES / "model_benchmarks",
            RUNTIME_TRACES / "model_lifecycle",
            RUNTIME_DIR / "approvals",
            RUNTIME_DIR / "downloads" / "models",
            RUNTIME_DIR / "downloads" / "repositories",
        ]:
            d.mkdir(parents=True, exist_ok=True)

        self._ensure_model_topology()
        self._ensure_model_stage_policy()
        self._ensure_provider_runtime_templates()
        self._ensure_model_providers()
        self._ensure_workflow()
        self._ensure_node_configs()
        self._ensure_runtime_templates()
        self._ensure_prompts()
        self._ensure_schemas()
        self._ensure_adapters()
        self._ensure_capability_routes()
        self._ensure_base_capabilities()
        self._ensure_environment()
        self._ensure_registry()
        self._ensure_datasets()


    def _ensure_model_topology(self) -> None:
        self.model_topology.ensure_defaults()


    def _ensure_model_stage_policy(self) -> None:
        self.model_stage_policy.ensure_defaults()


    def _ensure_provider_runtime_templates(self) -> None:
        source = Path("configs/provider_runtime_templates.seed.json")
        target = RUNTIME_GENERATED / "system_topology" / "provider_runtime_templates.json"
        if target.exists():
            return
        if source.exists():
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    def _ensure_model_providers(self) -> None:
        """Ensure provider config prefers the local base model qwen3:8b.

        Important: older runtimes may already have runtime/configs/models/providers.yaml.
        In that case we must merge/sync the base model settings instead of returning
        early; otherwise existing projects keep using qwen3:4b or OpenAI-first routes.
        """
        p = RUNTIME_CONFIGS / "models" / "providers.yaml"
        desired = self._default_model_providers_config()
        if p.exists():
            current = self.loader.load_yaml(p) or {}
            merged = self._merge_model_provider_defaults(current, desired)
            self.loader.save_yaml(p, merged)
            return
        self.loader.save_yaml(p, desired)

    def _default_model_providers_config(self) -> dict:
        return {
            "default_route": ["openai", "claude", "vllm", "ollama"],
            "routes": {
                "local_light": ["vllm", "ollama", "openai"],
                "local_capable": ["vllm", "ollama", "lmstudio", "openai"],
                "strong_reasoning": ["openai", "claude", "vllm", "ollama", "lmstudio"],
                "input_parsing": ["openai", "claude", "vllm", "ollama"],
                "intent_simple": ["openai", "claude", "vllm", "ollama"],
                "intent_complex": ["openai", "claude", "vllm", "ollama", "lmstudio"],
                "intent_recognition": ["openai", "claude", "vllm", "ollama"],
                "workflow_basic": ["openai", "claude", "vllm", "ollama"],
                "workflow_complex": ["openai", "claude", "vllm", "ollama", "lmstudio"],
                "workflow_planning": ["openai", "claude", "vllm", "ollama"],
                "semantic_grounding": ["openai", "claude", "vllm", "ollama", "lmstudio"],
                "tool_selection": ["openai", "claude", "vllm", "ollama"],
                "stable_synthesis": ["openai", "claude", "vllm", "ollama"],
                "stable_synthesis_strong": ["openai", "claude", "vllm", "ollama", "lmstudio"],
                "reasoning": ["openai", "claude", "vllm", "ollama"],
                # Code artifact generation uses code-specialized local models first.
                # The generic vision/reasoning model is kept later as fallback only.
                "code_generation": [
                    "vllm_coder",
                    "ollama_coder_qwen25",
                    "ollama_coder_deepseek",
                    "lmstudio_coder",
                    "openai"
                ],
                "adapter_generation": [
                    "vllm_coder",
                    "ollama_coder_qwen25",
                    "ollama_coder_deepseek",
                    "lmstudio_coder",
                    "openai"
                ],
                "schema_repair": [
                    "vllm_coder",
                    "ollama_coder_qwen25",
                    "ollama_coder_deepseek",
                    "openai"
                ],
                "api_discovery_local": ["vllm", "ollama"],
                "api_discovery_external": ["openai", "claude", "vllm", "ollama"],
                "fallback": ["openai", "claude", "vllm", "ollama"]
            },
            "role_model_preferences": {
                "information_retrieval_agent": ["structured_extraction", "reasoning"],
                "workflow_planning_agent": ["workflow_planning", "reasoning", "json_generation"],
                "integration_builder_agent": ["reasoning", "structured_extraction", "json_generation"],
                "code_generation_agent": [
                    "code_generation",
                    "python_generation",
                    "adapter_generation",
                    "schema_repair",
                    "structured_output",
                    "json_generation"
                ],
                "data_analysis_agent": ["structured_extraction", "reasoning"],
                "document_writer_agent": ["document_generation", "reasoning"],
                "human_interaction_agent": ["json_generation"],
                "vision_runtime_agent": ["vision", "screenshot_analysis", "ui_understanding", "reasoning"]
            },
            "providers": {
                "ollama": {
                    "enabled": True,
                    "type": "universal_model",
                    "protocol": "ollama_chat",
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
                    "model": "qwen3:8b",
                    "available_local_models": [
                        "qwen3-vl:8b-thinking",
                        "qwen3:32b",
                        "qwen3:14b",
                        "qwen3:8b",
                        "qwen3:4b",
                        "qwen2.5:3b",
                        "qwen3:1.7b",
                        "llama3.2:8b",
                        "llama3.2:3b"
                    ],
                    "fallback_models": [
                        "qwen3:32b",
                        "qwen3:14b",
                        "qwen3:8b",
                        "qwen3:4b",
                        "qwen2.5:3b",
                        "qwen3:1.7b",
                        "llama3.2:8b",
                        "llama3.2:3b"
                    ],
                    "model_tags": [
                        "reasoning",
                        "thinking",
                        "vision",
                        "screenshot_analysis",
                        "ui_understanding",
                        "structured_extraction",
                        "planning",
                        "json_generation",
                        "tool_selection",
                        "workflow_planning"
                    ],
                    "capabilities": [
                        "reasoning",
                        "vision",
                        "screenshot_analysis",
                        "ui_understanding",
                        "structured_extraction",
                        "json_generation",
                        "workflow_planning"
                    ],
                    "reasoning": {
                        "enabled": True,
                        "effort": "medium"
                    },
                    "timeout_seconds": 180,
                    "max_prompt_tokens": 10000,
                    "prompt_budget_safety_tokens": 1500,
                    "max_schema_chars": 8000,
                    "cache_enabled": True,
                    "auto_start": True,
                    "start_command": "{binary} serve",
                    "ready_timeout_seconds": 45,
                    "ready_poll_interval_seconds": 1,
                    "auto_pull_missing_model": True,
                    "pull_command": "{binary} pull {model}",
                    "pull_timeout_seconds": 3600
                },

                "ollama_coder_qwen25": {
                    "enabled": True,
                    "type": "universal_model",
                    "protocol": "ollama_chat",
                    "base_url": "http://127.0.0.1:11434",
                    "binary": "ollama",
                    "endpoint_strategy": "auto",
                    "chat_endpoint": "/api/chat",
                    "generate_endpoint": "/api/generate",
                    "model": "qwen2.5-coder:7b",
                    "fallback_models": [
                        "qwen2.5-coder:7b",
                        "qwen2.5-coder:14b",
                        "qwen2.5-coder:3b",
                        "qwen3:8b",
                        "qwen3:4b"
                    ],
                    "model_tags": [
                        "local",
                        "free",
                        "code_generation",
                        "python_generation",
                        "adapter_generation",
                        "schema_repair",
                        "structured_output",
                        "json_generation",
                        "tool_generation"
                    ],
                    "capabilities": [
                        "code_generation",
                        "python_generation",
                        "adapter_generation",
                        "schema_repair",
                        "structured_output",
                        "json_generation",
                        "tool_generation"
                    ],
                    "quality": {
                        "code_generation": 18,
                        "structured_output": 8
                    },
                    "priority": 8,
                    "reasoning": {
                        "enabled": False,
                        "effort": "low"
                    },
                    "timeout_seconds": 150,
                    "max_prompt_tokens": 8000,
                    "prompt_budget_safety_tokens": 1200,
                    "max_schema_chars": 7000,
                    "cache_enabled": True,
                    "auto_start": True,
                    "start_command": "{binary} serve",
                    "ready_timeout_seconds": 45,
                    "ready_poll_interval_seconds": 1,
                    "auto_pull_missing_model": True,
                    "pull_command": "{binary} pull {model}",
                    "pull_timeout_seconds": 3600
                },
                "ollama_coder_deepseek": {
                    "enabled": True,
                    "type": "universal_model",
                    "protocol": "ollama_chat",
                    "base_url": "http://127.0.0.1:11434",
                    "binary": "ollama",
                    "endpoint_strategy": "auto",
                    "chat_endpoint": "/api/chat",
                    "generate_endpoint": "/api/generate",
                    "model": "deepseek-coder-v2:16b",
                    "fallback_models": [
                        "deepseek-coder-v2:16b",
                        "deepseek-coder-v2:lite",
                        "qwen2.5-coder:7b",
                        "qwen3:8b"
                    ],
                    "model_tags": [
                        "local",
                        "free",
                        "code_generation",
                        "python_generation",
                        "adapter_generation",
                        "schema_repair",
                        "structured_output",
                        "json_generation",
                        "tool_generation"
                    ],
                    "capabilities": [
                        "code_generation",
                        "python_generation",
                        "adapter_generation",
                        "schema_repair",
                        "structured_output",
                        "json_generation",
                        "tool_generation"
                    ],
                    "quality": {
                        "code_generation": 20,
                        "structured_output": 7
                    },
                    "priority": 6,
                    "reasoning": {
                        "enabled": False,
                        "effort": "low"
                    },
                    "timeout_seconds": 180,
                    "max_prompt_tokens": 9000,
                    "prompt_budget_safety_tokens": 1200,
                    "max_schema_chars": 8000,
                    "cache_enabled": True,
                    "auto_start": True,
                    "start_command": "{binary} serve",
                    "ready_timeout_seconds": 45,
                    "ready_poll_interval_seconds": 1,
                    "auto_pull_missing_model": True,
                    "pull_command": "{binary} pull {model}",
                    "pull_timeout_seconds": 3600
                },
                "openai": {
                    "enabled": True,
                    "type": "universal_model",
                    "protocol": "openai_compatible",
                    "base_url": "https://api.openai.com",
                    "endpoint": "/v1/chat/completions",
                    "auth_type": "bearer_env",
                    "auth_env": "OPENAI_API_KEY",
                    "model": "gpt-4o-mini",
                    "timeout_seconds": 30,
                    "max_prompt_tokens": 12000,
                    "max_schema_chars": 12000,
                    "cache_enabled": True,
                    "interactive_key_required": True,
                    "role": "external_fallback",
                    "model_tags": ["reasoning", "json_generation", "tool_calling", "document_generation", "semantic_grounding", "workflow_planning", "evidence_verification", "stable_synthesis", "structured_output"],
                    "capabilities": ["reasoning", "json_generation", "tool_calling", "document_generation", "semantic_grounding", "workflow_planning", "evidence_verification", "stable_synthesis", "structured_output"],
                    "quality": {"semantic_grounding": 20, "workflow_planning": 16, "stable_synthesis": 16, "structured_output": 15},
                    "priority": 4
                },

                "claude": {
                    "enabled": False,
                    "type": "universal_model",
                    "protocol": "openai_compatible",
                    "base_url": "https://api.anthropic.com",
                    "endpoint": "/v1/chat/completions",
                    "auth_type": "bearer_env",
                    "auth_env": "ANTHROPIC_API_KEY",
                    "model": "claude-sonnet",
                    "timeout_seconds": 90,
                    "max_prompt_tokens": 12000,
                    "max_schema_chars": 12000,
                    "cache_enabled": True,
                    "interactive_key_required": True,
                    "role": "external_fallback",
                    "model_tags": ["reasoning", "json_generation", "document_generation", "stable_synthesis", "code_generation", "structured_output"],
                    "capabilities": ["reasoning", "json_generation", "document_generation", "stable_synthesis", "code_generation", "structured_output"],
                    "quality": {"stable_synthesis": 20, "code_generation": 20, "structured_output": 12},
                    "priority": 3
                },

                "vllm_coder": {
                    "enabled": True,
                    "type": "universal_model",
                    "protocol": "openai_compatible",
                    "base_url": "http://127.0.0.1:8002",
                    "endpoint": "/v1/chat/completions",
                    "model": "Qwen/Qwen2.5-Coder-7B-Instruct",
                    "timeout_seconds": 90,
                    "max_prompt_tokens": 12000,
                    "cache_enabled": True,
                    "response_format_json": True,
                    "model_tags": ["local", "code_generation", "python_generation", "adapter_generation", "structured_output", "json_generation"],
                    "capabilities": ["code_generation", "python_generation", "adapter_generation", "structured_output", "json_generation"],
                    "quality": {"code_generation": 18, "structured_output": 8},
                    "priority": 7
                },
                "lmstudio_coder": {
                    "enabled": False,
                    "type": "universal_model",
                    "protocol": "openai_compatible",
                    "base_url": "http://127.0.0.1:1234",
                    "endpoint": "/v1/chat/completions",
                    "model": "qwen2.5-coder-7b-instruct",
                    "timeout_seconds": 90,
                    "max_prompt_tokens": 12000,
                    "cache_enabled": True,
                    "response_format_json": True,
                    "model_tags": ["local", "code_generation", "python_generation", "adapter_generation", "structured_output", "json_generation"],
                    "capabilities": ["code_generation", "python_generation", "adapter_generation", "structured_output", "json_generation"],
                    "quality": {"code_generation": 16, "structured_output": 7},
                    "priority": 5
                },
                "vllm": {
                    "enabled": True,
                    "type": "universal_model",
                    "protocol": "openai_compatible",
                    "base_url": "http://127.0.0.1:8001",
                    "endpoint": "/v1/chat/completions",
                    "model": "Qwen/Qwen2.5-7B-Instruct",
                    "timeout_seconds": 60,
                    "max_prompt_tokens": 12000,
                    "cache_enabled": True,
                    "response_format_json": True,
                    "model_tags": ["local", "reasoning", "json_generation"],
                    "capabilities": ["reasoning", "json_generation"]
                },
                "lmstudio": {
                    "enabled": False,
                    "type": "universal_model",
                    "protocol": "openai_compatible",
                    "base_url": "http://127.0.0.1:1234",
                    "endpoint": "/v1/chat/completions",
                    "model": "local-model",
                    "timeout_seconds": 60,
                    "max_prompt_tokens": 12000,
                    "cache_enabled": True,
                    "response_format_json": True,
                    "model_tags": ["local", "reasoning", "json_generation"],
                    "capabilities": ["reasoning", "json_generation"]
                }
            },
            "policy": {
                "require_real_provider": True,
                "allow_placeholder_result": False,
                "prefer_local_base_model": False,
                "runtime_execution_policy": {
                    "source_of_truth": "runtime_execution_policy",
                    "default_mode": "api_only",
                    "local_enabled": False,
                    "api_only_when_local_disabled": True,
                    "api_provider_order": ["openai", "claude"],
                    "local_provider_order": ["vllm", "ollama"],
                    "local_code_provider_order": ["vllm_coder", "ollama_coder_qwen25", "ollama_coder_deepseek"],
                    "credential_recovery_enabled": True
                },
                "local_models_enabled": False,
                "local_provider_order": ["vllm", "ollama"],
                "api_only_when_local_disabled": True,
                "api_provider_order": ["openai", "claude"],
                "base_model_provider": "openai",
                "base_model": "Qwen/Qwen2.5-7B-Instruct",
                "local_fallback_provider": "ollama",
                "local_fallback_model": "qwen3:8b",
                "code_generation_provider": "vllm_coder",
                "code_generation_model": "Qwen/Qwen2.5-Coder-7B-Instruct",
                "code_generation_fallback_provider": "ollama_coder_qwen25",
                "code_generation_fallback_model": "qwen2.5-coder:7b",
                "external_provider_is_fallback": False
            }
        }

    def _merge_model_provider_defaults(self, current: dict, desired: dict) -> dict:
        current = dict(current or {})
        current["default_route"] = desired["default_route"]
        routes = dict(current.get("routes") or {})
        for key, value in desired.get("routes", {}).items():
            routes[key] = value
        current["routes"] = routes

        role_prefs = dict(current.get("role_model_preferences") or {})
        for key, value in desired.get("role_model_preferences", {}).items():
            role_prefs[key] = value
        current["role_model_preferences"] = role_prefs

        providers = dict(current.get("providers") or {})
        desired_providers = desired.get("providers", {})
        for provider_id, desired_provider in desired_providers.items():
            existing = dict(providers.get(provider_id) or {})
            merged = {**desired_provider, **existing}
            if provider_id in {"vllm", "vllm_coder", "ollama", "ollama_coder_qwen25", "ollama_coder_deepseek"}:
                # Force core runtime model lines while preserving user-specific
                # endpoint/binary/install overrides where possible.
                for key in [
                    "enabled", "type", "protocol", "model", "fallback_models",
                    "model_tags", "capabilities", "quality", "priority", "reasoning",
                    "timeout_seconds", "max_prompt_tokens",
                    "prompt_budget_safety_tokens", "max_schema_chars",
                    "cache_enabled", "auto_start", "auto_pull_missing_model",
                    "pull_timeout_seconds"
                ]:
                    if key in desired_provider:
                        merged[key] = desired_provider[key]
                for key in ["base_url", "binary", "chat_endpoint", "generate_endpoint", "endpoint_strategy", "start_command", "pull_command"]:
                    merged.setdefault(key, desired_provider.get(key))
            providers[provider_id] = merged
        current["providers"] = providers

        policy = dict(current.get("policy") or {})
        policy.update(desired.get("policy", {}))
        snapshot = self.runtime_execution_policy.snapshot(provider_config={"policy": policy})
        policy.update(snapshot.to_provider_policy())
        current["policy"] = policy
        current["default_route"] = snapshot.filter_route(current.get("default_route", []), current.get("providers", {})) or snapshot.api_provider_order
        routes = current.get("routes", {}) if isinstance(current.get("routes"), dict) else {}
        for route_name, route in list(routes.items()):
            if isinstance(route, list):
                routes[route_name] = snapshot.filter_route(route, current.get("providers", {})) or snapshot.api_provider_order
        current["routes"] = routes
        return current

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
                "version": "2.0",
                "executor_type": "llm_json",
                "system": (
                    "You are a generic input parsing engine. Return JSON only according to the output schema. "
                    "Only parse the raw input. Do not generate tasks, workflow, tools, APIs, providers, or execution decisions."
                ),
                "user_template": (
                    "User input: {{ user_input }}\n"
                    "Runtime context: {{ runtime_context }}\n"
                    "Previous results: {{ previous_results }}\n"
                    "Correction memory: {{ correction_memory }}"
                ),
                "runtime_rules": [
                    "Only output fields needed for input parsing.",
                    "Do not output top-level tasks.",
                    "Do not output planned_steps, required_capabilities, tool names, API names, provider names, or execution decisions.",
                    "Extract parsed_entities, semantic modifiers, constraints, and temporal expressions from the original input.",
                    "If runtime_context can safely normalize a relative expression, include the normalized value as parsed data while preserving the original expression.",
                ],
                "output_contract": {
                    "language": "string",
                    "original_input": "string",
                    "parsed_entities": "object",
                    "semantic_modifiers": "array",
                    "constraints": "object",
                    "temporal_expressions": "array",
                    "missing_information": "array",
                    "safety_notes": "array"
                }
            },
            "intent_recognition": {
                "id": "intent_recognition_prompt",
                "version": "2.0",
                "executor_type": "llm_json",
                "system": (
                    "You are a generic intent recognition engine. Return JSON only. "
                    "Only classify and summarize intent. Do not generate tasks, workflow, tools, APIs, providers, or execution decisions."
                ),
                "user_template": (
                    "User input: {{ user_input }}\n"
                    "Runtime context: {{ runtime_context }}\n"
                    "Previous results: {{ previous_results }}\n"
                    "Correction memory: {{ correction_memory }}"
                ),
                "runtime_rules": [
                    "Only output fields needed for intent recognition.",
                    "Do not output top-level tasks.",
                    "Do not output planned_steps, required_capabilities, tool names, API names, provider names, or execution decisions.",
                    "Use input_parsing results when available instead of re-parsing the raw input.",
                    "Do not ask human questions unless intent itself is ambiguous.",
                ],
                "output_contract": {
                    "intent_type": "string",
                    "intent_summary": "string",
                    "normalized_intent": "object",
                    "confidence": "object",
                    "human_review": "object"
                }
            },
            "workflow_planning": {
                "id": "workflow_planning_prompt",
                "version": "2.0",
                "executor_type": "llm_json",
                "system": (
                    "You are a generic workflow planner. Produce executable planned_steps from previous structured results. "
                    "Return JSON only. Use generic capabilities only; do not choose concrete tools, APIs, providers, libraries, repositories, or implementation files."
                ),
                "user_template": (
                    "User input: {{ user_input }}\n"
                    "Runtime context: {{ runtime_context }}\n"
                    "Previous results: {{ previous_results }}\n"
                    "Correction memory: {{ correction_memory }}"
                ),
                "runtime_rules": [
                    "Only workflow_planning may create planned_steps.",
                    "planned_steps must be executable step objects, not strings.",
                    "Copy normalized entities from upstream nodes; do not invent stale values or re-normalize already resolved values.",
                    "Prefer execution_strategy over concrete capabilities: [local_knowledge, web_evidence, tool_generation].",
                    "Do not choose concrete tools, APIs, providers, or generated implementations in planning.",
                    "If required_capability is retained for schema compatibility, keep it generic and do not encode provider/API names.",
                    "Do not request human_interaction for data already available from upstream nodes.",
                ],
                "output_contract": {
                    "planned_steps": "array",
                    "blocking_missing_information": "array",
                    "required_capabilities": "array",
                    "execution_strategy": "array",
                    "human_interaction": "object"
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
                "required": ["language", "original_input", "parsed_entities", "missing_information"],
                "properties": {
                    "language": {"type": "string"},
                    "original_input": {"type": "string"},
                    "parsed_entities": {"type": "object", "additionalProperties": True},
                    "semantic_modifiers": {"type": "array", "items": {"type": "string"}},
                    "constraints": {"type": "object", "additionalProperties": True},
                    "temporal_expressions": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                    "missing_information": {"type": "array", "items": {"type": "string"}},
                    "safety_notes": {"type": "array", "items": {"type": "string"}}
                },
                "not": {"required": ["tasks"]},
                "additionalProperties": True
            },
            "intent_recognition": {
                "type": "object",
                "required": ["intent_type", "confidence"],
                "properties": {
                    "intent_type": {"type": "string"},
                    "intent_summary": {"type": "string"},
                    "normalized_intent": {"type": "object", "additionalProperties": True},
                    "confidence": {
                        "oneOf": [
                            {"type": "number"},
                            {
                                "type": "object",
                                "properties": {
                                    "overall": {"type": "number"},
                                    "intent": {"type": "number"},
                                    "parameter_understanding": {"type": "number"},
                                    "execution_readiness": {"type": "number"}
                                },
                                "additionalProperties": True
                            }
                        ]
                    },
                    "human_review": {"type": "object", "additionalProperties": True},
                    "reason": {"type": "string"}
                },
                "not": {"required": ["tasks"]},
                "additionalProperties": True
            },
            "workflow_planning": {
                "type": "object",
                "required": ["planned_steps"],
                "properties": {
                    "planned_steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": [
                                "step_id", "step_type", "objective", "input_from",
                                "parameters", "execution_ready",
                                "human_interaction", "next_action"
                            ],
                            "properties": {
                                "step_id": {"type": "string"},
                                "step_type": {"type": "string"},
                                "task_id": {"type": "string"},
                                "task_type": {"type": "string"},
                                "action": {"type": "string"},
                                "objective": {"type": "string"},
                                "input_from": {"type": "array", "items": {"type": "string"}},
                                "parameters": {
                                    "type": "object",
                                    "properties": {
                                        "known": {"type": "object", "additionalProperties": True},
                                        "optional": {"type": "object", "additionalProperties": True},
                                        "missing_required": {"oneOf": [{"type": "array"}, {"type": "object"}]}
                                    },
                                    "additionalProperties": True
                                },
                                "required_capability": {"oneOf": [{"type": "string"}, {"type": "object"}]},
                                "execution_strategy": {"type": "array", "items": {"type": "string"}},
                                "execution_ready": {"type": "boolean"},
                                "human_interaction": {"type": "object", "additionalProperties": True},
                                "next_action": {"type": "string"},
                                "depends_on": {"type": "array"},
                                "requires_human_confirmation": {"type": "boolean"}
                            },
                            "additionalProperties": True
                        }
                    },
                    "blocking_missing_information": {"oneOf": [{"type": "array"}, {"type": "object"}]},
                    "required_capabilities": {"type": "array"},
                    "execution_strategy": {"type": "array", "items": {"type": "string"}},
                    "human_interaction": {"type": "object"}
                },
                "additionalProperties": True
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
                "provider_route": ["vllm", "ollama", "openai"],
                "route_name": "input_parsing",
                "model_complexity": "low",
                "model_capabilities": ["json_generation", "structured_extraction"],
                "prompt": "runtime/generated/prompts/input_parsing.yaml",
                "output_schema": "runtime/generated/schemas/input_parsing.schema.json",
                "json_mode": True
            },
            "intent_recognition": {
                "adapter_id": "intent_recognition_adapter",
                "type": "llm_json",
                "provider_route": ["vllm", "ollama", "openai"],
                "route_name": "intent_simple",
                "model_complexity": "low",
                "model_capabilities": ["json_generation", "structured_extraction"],
                "prompt": "runtime/generated/prompts/intent_recognition.yaml",
                "output_schema": "runtime/generated/schemas/intent_recognition.schema.json",
                "json_mode": True
            },
            "workflow_planning": {
                "adapter_id": "workflow_planning_adapter",
                "type": "llm_json",
                "provider_route": ["vllm", "ollama", "openai"],
                "route_name": "workflow_basic",
                "model_complexity": "medium",
                "model_capabilities": ["workflow_planning", "json_generation"],
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
