from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from ai_core.modules.module_registry import RuntimeModuleRegistry


class RuntimeModuleLoader:
    """
    Generic runtime module loader.

    Loads approved/enabled generated modules by capability.
    Does not know module business logic.
    """

    def __init__(self) -> None:
        self.registry = RuntimeModuleRegistry()

    def load_by_capability(self, capability: str) -> Any | None:
        record = self.registry.find_by_capability(capability, include_non_executable=False)
        if not record:
            return None
        if record.get("status") not in {"enabled", "approved", "active"}:
            return None

        entrypoint = Path(record.get("entrypoint", ""))
        if not entrypoint.exists():
            return None

        spec = importlib.util.spec_from_file_location(record["module_id"], entrypoint)
        if not spec or not spec.loader:
            return None

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
