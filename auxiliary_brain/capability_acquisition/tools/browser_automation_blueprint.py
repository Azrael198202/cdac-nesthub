from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ai_core.config.paths import RUNTIME_GENERATED


class BrowserAutomationBlueprintBuilder:
    """
    Generic browser automation blueprint writer.

    IMPORTANT:
    This class must not parse business language, time expressions, websites,
    domain-specific words, workflows, or action semantics.

    It only persists structured browser automation metadata that was already
    produced by runtime planning / LLM / generated configs.

    ai_core responsibility:
      - create directory
      - write blueprint JSON
      - write safe placeholder tool
      - keep safety defaults generic

    Runtime-generated responsibility:
      - site/url extraction
      - temporal metadata extraction
      - action semantics
      - selector discovery strategy
      - domain-specific constraints
    """

    def __init__(self) -> None:
        self.dir = RUNTIME_GENERATED / "browser_blueprints"
        self.dir.mkdir(parents=True, exist_ok=True)

    def create_blueprint(
        self,
        *,
        user_input: str,
        step: dict[str, Any],
        capability: str = "browser_automation",
    ) -> dict[str, Any]:
        metadata = self._runtime_metadata(step)

        blueprint_id = (
            metadata.get("blueprint_id")
            or f"browser_blueprint_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"
        )

        blueprint = {
            "blueprint_id": blueprint_id,
            "capability": capability,
            "status": "blueprint_generated",
            "created_at": datetime.utcnow().isoformat(),
            "source_user_input": user_input,
            "source_step": step,
            "runtime_metadata": metadata,
            "credential_policy": metadata.get("credential_policy", self._default_credential_policy()),
            "safety_policy": metadata.get("safety_policy", self._default_safety_policy()),
            "temporal_triggers": metadata.get("temporal_triggers", metadata.get("temporal_plan", [])),
            "browser_steps": metadata.get("browser_steps", []),
            "playwright_generation": metadata.get("playwright_generation", self._default_playwright_generation(blueprint_id)),
            "notes": [
                "This blueprint is generic.",
                "Any business-specific page/action/temporal semantics must be generated outside ai_core and passed in source_step/runtime_metadata.",
                "No irreversible browser action should execute without explicit human confirmation unless runtime policy explicitly allows it.",
            ],
        }

        out_dir = self.dir / blueprint_id
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "blueprint.json").write_text(json.dumps(blueprint, ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / "README.md").write_text(self._readme(blueprint), encoding="utf-8")
        (out_dir / "tool.py").write_text(self._safe_placeholder_py(blueprint_id), encoding="utf-8")

        return {
            "blueprint_id": blueprint_id,
            "blueprint_dir": str(out_dir),
            "blueprint": blueprint,
        }

    def _runtime_metadata(self, step: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(step, dict):
            return {}

        for key in [
            "browser_blueprint",
            "browser_automation",
            "automation_blueprint",
            "runtime_metadata",
            "metadata",
        ]:
            value = step.get(key)
            if isinstance(value, dict):
                return value

        parameters = step.get("parameters")
        if isinstance(parameters, dict):
            for key in [
                "browser_blueprint",
                "browser_automation",
                "automation_blueprint",
                "runtime_metadata",
                "metadata",
            ]:
                value = parameters.get(key)
                if isinstance(value, dict):
                    return value

        return {}

    def _default_credential_policy(self) -> dict[str, Any]:
        return {
            "credential_required": "runtime_decides",
            "store_location": "runtime/configs/secrets/secrets.json",
            "ask_user_if_missing": True,
            "never_log_secret_values": True,
        }

    def _default_safety_policy(self) -> dict[str, Any]:
        return {
            "requires_human_confirmation_before_irreversible_action": True,
            "can_prepare_page": True,
            "can_perform_irreversible_action_without_confirmation": False,
            "can_mutate_external_system_without_confirmation": False,
            "policy_source": "generic_core_default",
        }

    def _default_playwright_generation(self, blueprint_id: str) -> dict[str, Any]:
        return {
            "target_file": f"runtime/generated/browser_blueprints/{blueprint_id}/tool.py",
            "language": "python",
            "library": "playwright",
            "generate_after_review": True,
        }

    def _readme(self, blueprint: dict[str, Any]) -> str:
        return (
            "# Browser Automation Blueprint\n\n"
            "Runtime-generated browser automation blueprint.\n\n"
            "This file is generic. Domain-specific URL, temporal metadata, and action semantics must be generated by runtime planning, not hardcoded in ai_core.\n"
        )

    def _safe_placeholder_py(self, blueprint_id: str) -> str:
        return (
            f'"""Safe placeholder for browser automation blueprint {blueprint_id}."""\n\n'
            "from typing import Any\n\n\n"
            "def run(input_data: dict[str, Any]) -> dict[str, Any]:\n"
            "    return {\n"
            '        "status": "blueprint_only",\n'
            f'        "blueprint_id": "{blueprint_id}",\n'
            '        "message": "Browser automation blueprint exists. Real Playwright code is not generated or approved yet.",\n'
            '        "requires_human_confirmation": True,\n'
            "    }\n"
        )
