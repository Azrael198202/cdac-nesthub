from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai_core.config.paths import CONFIGS_DIR, RUNTIME_GENERATED


class RuntimeCapabilityTemplateStore:
    """Load runtime capability acquisition templates from runtime-owned areas.

    ai_core must not be the permanent home for concrete capability templates.
    Concrete capability templates are runtime artifacts and should live under
    runtime/generated.  The legacy configs path is kept only as a compatibility
    source for older projects, and should normally contain no concrete templates.
    """

    def __init__(self, *, explicit_path: Path | None = None) -> None:
        self.explicit_path = explicit_path
        self.runtime_template_dir = RUNTIME_GENERATED / "capability_templates"
        self.runtime_system_template_path = RUNTIME_GENERATED / "system_topology" / "runtime_capability_templates.json"
        self.runtime_contract_template_path = RUNTIME_GENERATED / "contracts" / "runtime_capability_templates.json"
        self.legacy_config_template_path = CONFIGS_DIR / "runtime_capability_templates.json"

    def candidate_paths(self) -> list[Path]:
        if self.explicit_path is not None:
            return [self.explicit_path]
        paths: list[Path] = []
        if self.runtime_template_dir.exists():
            paths.extend(sorted(self.runtime_template_dir.glob("*.json")))
        paths.extend([
            self.runtime_system_template_path,
            self.runtime_contract_template_path,
            self.legacy_config_template_path,
        ])
        seen: set[str] = set()
        unique: list[Path] = []
        for path in paths:
            key = str(path.resolve()) if path.exists() else str(path)
            if key in seen:
                continue
            seen.add(key)
            unique.append(path)
        return unique

    def load_templates(self) -> list[dict[str, Any]]:
        templates: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for path in self.candidate_paths():
            for template in self._load_templates_from_path(path):
                template_id = str(template.get("template_id") or "").strip()
                if template_id and template_id in seen_ids:
                    continue
                if template_id:
                    seen_ids.add(template_id)
                templates.append(template)
        return templates

    def _load_templates_from_path(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8") or "{}")
        except Exception:
            return []
        templates = data.get("templates") if isinstance(data, dict) else data
        if not isinstance(templates, list):
            return []
        return [item for item in templates if isinstance(item, dict)]
