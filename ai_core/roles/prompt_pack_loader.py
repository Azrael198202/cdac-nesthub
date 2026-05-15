from __future__ import annotations

from typing import Any

from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import RUNTIME_CONFIGS


class PromptPackLoader:
    """Load role-scoped prompt packs from runtime configuration.

    Missing runtime config is not fatal. ai_core provides safe generic defaults,
    while deployments can override them under runtime/configs/roles/prompt_packs.yaml.
    """

    DEFAULT_PACKS: dict[str, dict[str, Any]] = {
        "information_retrieval_agent": {
            "system_addendum": "Act as a compact information retrieval runtime role. Use only scoped evidence and required parameters. Do not request optional credentials while public evidence is sufficient.",
            "runtime_rules": [
                "Use compact evidence summaries instead of raw pages.",
                "Check whether evidence covers required parameters before answering.",
                "Do not include internal traces in final outputs.",
            ],
        },
        "code_generation_agent": {
            "system_addendum": "Act as a compact code generation runtime role. Generate only the minimal artifact required by the contract and avoid unnecessary dependencies.",
            "runtime_rules": [
                "Preserve the required run(payload) contract when generating executable artifacts.",
                "Prefer deterministic adapters when enough evidence already exists.",
                "Do not include raw discovery traces unless explicitly required.",
            ],
        },
        "integration_builder_agent": {
            "system_addendum": "Act as a compact integration builder runtime role. Focus on protocol, authentication, parameters, verification, and adapter contract.",
            "runtime_rules": [
                "Do not treat documentation pages as JSON endpoints without verification.",
                "Separate no-credential paths from credential-protected optional upgrades.",
                "Return minimal adapter requirements only.",
            ],
        },
        "workflow_planning_agent": {
            "system_addendum": "Act as a compact workflow planning runtime role. Build only the next executable steps required by the current intent.",
            "runtime_rules": [
                "Do not select tools unless the node is responsible for tool selection.",
                "Do not ask for fields already resolved by prior nodes.",
                "Keep planned steps minimal and schema-valid.",
            ],
        },
        "human_interaction_agent": {
            "system_addendum": "Act as a compact human interaction runtime role. Ask only for truly required user input and mark secrets as secret fields.",
            "runtime_rules": [
                "Credential input must be optional when no-credential alternatives remain.",
                "Do not expose secret values in traces or final output.",
            ],
        },
        "general_runtime_agent": {
            "system_addendum": "Act as a compact runtime role. Follow the schema and use only the scoped context provided.",
            "runtime_rules": [
                "Prefer compact context over full trace dumps.",
                "Return valid JSON only when schema-bound.",
            ],
        },
    }

    def __init__(self) -> None:
        self.loader = ConfigLoader()

    def load(self, role_id: str) -> dict[str, Any]:
        packs = dict(self.DEFAULT_PACKS)
        path = RUNTIME_CONFIGS / "roles" / "prompt_packs.yaml"
        if path.exists():
            try:
                loaded = self.loader.load_yaml(path) or {}
                if isinstance(loaded, dict):
                    runtime_packs = loaded.get("prompt_packs", loaded)
                    if isinstance(runtime_packs, dict):
                        for key, value in runtime_packs.items():
                            if isinstance(value, dict):
                                packs[key] = {**packs.get(key, {}), **value}
            except Exception:
                # Prompt pack loading must never block runtime execution.
                pass
        return packs.get(role_id, packs["general_runtime_agent"])
