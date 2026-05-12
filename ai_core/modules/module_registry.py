from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_REGISTRY


class RuntimeModuleRegistry:
    """
    Generic runtime module registry.

    ai_core does not know scheduler/notification/web_query/etc.
    It only registers generated modules by capability and metadata.
    """

    def __init__(self) -> None:
        RUNTIME_REGISTRY.mkdir(parents=True, exist_ok=True)
        self.registry_path = RUNTIME_REGISTRY / "module_registry.json"
        if not self.registry_path.exists():
            self.registry_path.write_text("{}", encoding="utf-8")

    def load(self) -> dict[str, Any]:
        try:
            return json.loads(self.registry_path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError:
            return {}

    def save(self, registry: dict[str, Any]) -> None:
        self.registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")

    def register(
        self,
        *,
        module_id: str,
        capability: str,
        module_dir: str | Path,
        status: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        registry = self.load()
        module_dir = Path(module_dir)

        record = {
            "module_id": module_id,
            "capability": capability,
            "capabilities": [capability],
            "status": status,
            "module_dir": str(module_dir),
            "module_spec": str(module_dir / "module.json"),
            "entrypoint": str(module_dir / "module.py"),
            "metadata": metadata or {},
            "updated_at": datetime.utcnow().isoformat(),
        }
        registry[module_id] = record
        self.save(registry)
        return record

    def find_by_capability(self, capability: str) -> dict[str, Any] | None:
        registry = self.load()
        for record in registry.values():
            if capability == record.get("capability"):
                return record
            if capability in record.get("capabilities", []):
                return record
        return None
