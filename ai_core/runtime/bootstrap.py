from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path

from ai_core.runtime.paths import RUNTIME_DIR, ensure_runtime_dirs
from ai_core.runtime.file_store import FileStore


@dataclass
class BootstrapStatus:
    created: bool
    provider_ready: bool
    provider: str
    message: str


class RuntimeBootstrapper:
    """Creates only generic runtime infrastructure.

    This class must not know any business task names. It creates reusable
    model route, orchestration, validation and UI-support configuration.
    """

    def __init__(self) -> None:
        self.store = FileStore()

    def bootstrap(self) -> BootstrapStatus:
        ensure_runtime_dirs()
        created = False
        marker = RUNTIME_DIR / ".bootstrapped"
        if not marker.exists():
            self._write_default_configs()
            marker.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
            created = True
        provider = os.getenv("AI_CORE_PROVIDER", "auto")
        provider_ready = bool(os.getenv("OPENAI_API_KEY")) or provider == "ollama" or os.getenv("AI_CORE_ALLOW_LOCAL_RULES") == "1"
        message = "runtime initialized" if created else "runtime already initialized"
        return BootstrapStatus(created=created, provider_ready=provider_ready, provider=provider, message=message)

    def _write_default_configs(self) -> None:
        self.store.write_yaml(
            RUNTIME_DIR / "configs/models/model_routes.yaml",
            {
                "version": "1.0",
                "selection_order": ["local_rules", "ollama", "openai"],
                "providers": {
                    "local_rules": {
                        "enabled": True,
                        "type": "builtin_validator",
                        "purpose": "schema repair and safety checks only",
                    },
                    "ollama": {
                        "enabled": True,
                        "base_url": "http://127.0.0.1:11434",
                        "model": os.getenv("AI_CORE_OLLAMA_MODEL", "qwen3:4b"),
                    },
                    "openai": {
                        "enabled": True,
                        "model": os.getenv("AI_CORE_OPENAI_MODEL", "gpt-4o-mini"),
                        "api_key_env": "OPENAI_API_KEY",
                    },
                },
            },
        )
        self.store.write_yaml(
            RUNTIME_DIR / "configs/workflows/base_orchestration.yaml",
            {
                "workflow_id": "base_orchestration",
                "name": "Base Config Driven Orchestration",
                "nodes": [
                    {"id": "input_parsing", "type": "llm_json", "prompt": "input_parsing.yaml", "human_review": True},
                    {"id": "intent_recognition", "type": "llm_json", "prompt": "intent_recognition.yaml", "human_review": True},
                    {"id": "context_awareness", "type": "knowledge_lookup", "human_review": False},
                    {"id": "workflow_planning", "type": "llm_json", "prompt": "workflow_planning.yaml", "human_review": True},
                    {"id": "execution", "type": "dynamic_execution", "human_review": True},
                    {"id": "feedback_learning", "type": "learning", "human_review": False},
                    {"id": "output", "type": "final_output", "human_review": False},
                ],
            },
        )
        prompts = {
            "input_parsing.yaml": "Analyze the user input generically. Return JSON with language, cleaned_input, possible_entities, and ambiguity_notes. Do not invent facts.",
            "intent_recognition.yaml": "Classify the user's request generically. Return JSON with intent_label, confidence, required_capabilities, required_tools, risks, and missing_information. Do not use hardcoded domain assumptions.",
            "workflow_planning.yaml": "Create a generic execution plan from the recognized intent and context. Return JSON with steps, dependencies, required_tools, approval_points, and validation_rules. Do not fabricate external results.",
            "external_review.yaml": "Review the previous result. Return JSON with pass, reason, recommended_action, and improved_result when possible. Recommended action must be one of: continue_local, use_local_model, find_hf_model, use_external_api, ask_human.",
        }
        for name, text in prompts.items():
            self.store.write_yaml(RUNTIME_DIR / "configs/prompts" / name, {"version": "1.0", "template": text})
        self.store.write_yaml(
            RUNTIME_DIR / "configs/security/approval.yaml",
            {
                "default_human_review": True,
                "risky_actions_require_approval": True,
                "external_side_effects_require_approval": True,
            },
        )
        self.store.write_yaml(
            RUNTIME_DIR / "configs/tools/tool_policy.yaml",
            {
                "dynamic_tools_enabled": True,
                "no_fake_results": True,
                "unknown_tool_behavior": "ask_human_or_generate_config",
            },
        )
