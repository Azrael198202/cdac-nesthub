from __future__ import annotations

from typing import Any

from ai_core.config.io import write_yaml
from ai_core.config.paths import RUNTIME_CAPABILITIES_DIR, RUNTIME_INTENTS_DIR, RUNTIME_PROMPTS_DIR, RUNTIME_WORKFLOWS_DIR


class RuntimeConfigGenerator:
    """Generate missing runtime configs from observed tasks. ai_core code remains unchanged."""

    def ensure_basic_orchestration(self) -> None:
        workflow_file = RUNTIME_WORKFLOWS_DIR / "base_orchestration.yaml"
        if not workflow_file.exists():
            write_yaml(workflow_file, {
                "workflow_id": "base_orchestration",
                "nodes": [
                    {"id": "input_parsing", "type": "llm_step"},
                    {"id": "intent_recognition", "type": "llm_step"},
                    {"id": "context_awareness", "type": "knowledge_memory_step"},
                    {"id": "workflow_planning", "type": "llm_step"},
                    {"id": "execution", "type": "tool_step"},
                    {"id": "feedback_learning", "type": "learning_step"},
                    {"id": "output", "type": "output_step"},
                ],
                "verification_loop": "knowledge_local_selfcheck_human_external_retry_save",
            })
        caps_file = RUNTIME_CAPABILITIES_DIR / "task_capability_map.yaml"
        if not caps_file.exists():
            write_yaml(caps_file, {
                "input_parsing": ["text_normalization", "json_output"],
                "intent_recognition": ["classification", "json_output"],
                "context_awareness": ["memory", "rag"],
                "workflow_planning": ["workflow_planning", "reasoning", "json_output"],
                "execution": ["tool_calling", "approval"],
                "feedback_learning": ["learning", "trace", "finetune_dataset"],
            })

    def save_intent_config(self, intent: dict[str, Any]) -> None:
        name = intent.get("intent_type", "unknown_intent")
        write_yaml(RUNTIME_INTENTS_DIR / f"{name}.yaml", intent)

    def save_prompt(self, step: str, prompt: str) -> None:
        path = RUNTIME_PROMPTS_DIR / f"{step}.yaml"
        if not path.exists():
            write_yaml(path, {"id": step, "version": "runtime-generated-1", "template": prompt})

    def save_workflow(self, workflow: dict[str, Any]) -> None:
        workflow_id = workflow.get("workflow_id", "generated_workflow")
        write_yaml(RUNTIME_WORKFLOWS_DIR / f"{workflow_id}.yaml", workflow)
