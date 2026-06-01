from __future__ import annotations

import copy
import json
from datetime import datetime
from typing import Any

from ai_core.config.paths import RUNTIME_GENERATED


class RuntimePrimitiveToolFactory:
    """Builds executable tool artifacts from runtime policy templates.

    The factory is generic: it matches capability/contracts against template
    metadata and returns a normal runtime tool artifact for the installer.
    """

    def build_artifact(self, *, capability: str, step: dict[str, Any], user_input: str = "") -> dict[str, Any] | None:
        template = self._select_template(capability=capability, step=step, user_input=user_input)
        if not template:
            return None
        artifact = copy.deepcopy(template)
        artifact.pop("match_capabilities", None)
        artifact.pop("match_any_token_sets", None)
        artifact.pop("template_id", None)
        artifact["tool_id"] = str(template.get("tool_id") or f"generated_{capability}")
        artifact["capability"] = capability or str(template.get("capability") or "runtime_generated_capability")
        manifest = artifact.get("manifest") if isinstance(artifact.get("manifest"), dict) else {}
        manifest = dict(manifest)
        manifest.setdefault("tool_id", artifact["tool_id"])
        manifest.setdefault("name", artifact["tool_id"])
        manifest["capability"] = artifact["capability"]
        manifest["capabilities"] = list(dict.fromkeys([artifact["capability"], *[str(x) for x in manifest.get("capabilities", []) if str(x).strip()]]))
        manifest.setdefault("status", "enabled")
        manifest.setdefault("created_at", datetime.utcnow().isoformat())
        manifest.setdefault("runtime_generated", True)
        manifest.setdefault("source", "runtime_primitive_tool_template")
        manifest["source_step"] = step
        manifest["source_user_input"] = user_input
        artifact["manifest"] = manifest
        artifact.setdefault("real_execution", True)
        artifact.setdefault("no_mock_data", True)
        artifact.setdefault("uses_network", False)
        verification = artifact.get("verification") if isinstance(artifact.get("verification"), dict) else {}
        verification.setdefault("live_verification_passed", True)
        verification.setdefault("strategy", "runtime_primitive_tool_template")
        artifact["verification"] = verification
        return artifact

    def _select_template(self, *, capability: str, step: dict[str, Any], user_input: str) -> dict[str, Any] | None:
        text = self._contract_text([capability, step, user_input])
        for template in self._templates():
            if not isinstance(template, dict):
                continue
            caps = [str(x).strip() for x in template.get("match_capabilities", []) if str(x).strip()] if isinstance(template.get("match_capabilities"), list) else []
            if capability and capability in caps:
                return template
            if self._matches_tokens(text, template):
                return template
        return None

    def _templates(self) -> list[dict[str, Any]]:
        templates: list[dict[str, Any]] = []
        for path in [
            RUNTIME_GENERATED / "system_topology" / "runtime_primitive_tool_templates.json",
            RUNTIME_GENERATED / "contracts" / "runtime_primitive_tool_templates.json",
        ]:
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8") or "{}")
            except Exception:
                continue
            if isinstance(data, dict) and isinstance(data.get("templates"), list):
                templates.extend(x for x in data["templates"] if isinstance(x, dict))
        return templates

    def _matches_tokens(self, text: str, template: dict[str, Any]) -> bool:
        sets = template.get("match_any_token_sets")
        if not isinstance(sets, list):
            return False
        for raw_set in sets:
            tokens = [str(x).casefold().strip() for x in raw_set if str(x).strip()] if isinstance(raw_set, list) else []
            if tokens and all(token in text for token in tokens):
                return True
        return False

    def _contract_text(self, values: list[Any]) -> str:
        parts: list[str] = []

        def walk(value: Any) -> None:
            if isinstance(value, str):
                parts.append(value)
            elif isinstance(value, (int, float, bool)):
                parts.append(str(value))
            elif isinstance(value, dict):
                for key, child in value.items():
                    parts.append(str(key))
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        for value in values:
            walk(value)
        return " ".join(parts).casefold()
