from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_REGISTRY


class RuntimeModuleRegistry:
    """
    Generic runtime module registry.

    ai_core does not know domain-specific module types
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

    def find_by_capability(self, capability: str, *, include_non_executable: bool = True) -> dict[str, Any] | None:
        registry = self.load()
        matches = []
        for record in registry.values():
            if capability == record.get("capability") or capability in record.get("capabilities", []):
                matches.append(record)
        if not matches:
            return None

        priority = {"active": 0, "enabled": 1, "approved": 2, "verified": 3, "blueprint_generated": 50, "disabled": 99}
        matches.sort(key=lambda r: (priority.get(str(r.get("status") or "").lower(), 40), str(r.get("updated_at") or "")), reverse=False)
        # Prefer executable statuses first. Within the same status group prefer the latest record.
        matches = sorted(matches, key=lambda r: priority.get(str(r.get("status") or "").lower(), 40))
        grouped = [r for r in matches if priority.get(str(r.get("status") or "").lower(), 40) == priority.get(str(matches[0].get("status") or "").lower(), 40)]
        if grouped:
            latest = sorted(grouped, key=lambda r: str(r.get("updated_at") or ""), reverse=True)[0]
            rest = [r for r in matches if r is not latest]
            matches = [latest] + rest
        if include_non_executable:
            return matches[0]
        for record in matches:
            if str(record.get("status") or "").lower() in {"active", "enabled", "approved", "verified"}:
                return record
        return None

    def find_all_by_capability(self, capability: str) -> list[dict[str, Any]]:
        registry = self.load()
        return [r for r in registry.values() if capability == r.get("capability") or capability in r.get("capabilities", [])]

    def update_status(self, module_id: str, status: str, *, reason: str | None = None) -> dict[str, Any] | None:
        registry = self.load()
        record = registry.get(module_id)
        if not isinstance(record, dict):
            return None
        record["status"] = status
        record["updated_at"] = datetime.utcnow().isoformat()
        if reason:
            record.setdefault("metadata", {})["status_reason"] = reason
        registry[module_id] = record
        self.save(registry)
        return record
