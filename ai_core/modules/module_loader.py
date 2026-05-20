from __future__ import annotations

import importlib
import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from ai_core.modules.module_registry import RuntimeModuleRegistry
from ai_core.runtime.environment.permission_policy import RuntimePermissionPolicy


class RuntimeModuleLoader:
    """
    Generic runtime module loader.

    Loads approved/enabled generated modules by capability.
    Does not know module business logic.

    If a generated module declares or imports an optional Python dependency that
    is missing in the host runtime, the loader performs one generic dependency
    recovery attempt under the runtime permission policy, then retries import.
    This is intentionally capability-neutral.
    """

    def __init__(self) -> None:
        self.registry = RuntimeModuleRegistry()
        self.policy = RuntimePermissionPolicy.from_env()

    def load_by_capability(self, capability: str) -> Any | None:
        record = self.registry.find_by_capability(capability, include_non_executable=False)
        if not record:
            return None
        if record.get("status") not in {"enabled", "approved", "active"}:
            return None

        entrypoint = Path(record.get("entrypoint", ""))
        if not entrypoint.exists():
            return None

        return self._load_module_with_recovery(record=record, entrypoint=entrypoint)

    def _load_module_with_recovery(self, *, record: dict[str, Any], entrypoint: Path) -> Any | None:
        try:
            return self._load_module(record=record, entrypoint=entrypoint)
        except ModuleNotFoundError as exc:
            missing = self._missing_module_name(exc)
            if not missing or not self.policy.can_execute(kind="install"):
                raise
            if not self._install_python_package(missing):
                raise
            importlib.invalidate_caches()
            return self._load_module(record=record, entrypoint=entrypoint)

    def _load_module(self, *, record: dict[str, Any], entrypoint: Path) -> Any | None:
        spec = importlib.util.spec_from_file_location(record["module_id"], entrypoint)
        if not spec or not spec.loader:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _missing_module_name(self, exc: ModuleNotFoundError) -> str:
        name = getattr(exc, "name", "") or ""
        if name:
            return str(name).split(".")[0]
        match = re.search(r"No module named ['\"]([^'\"]+)['\"]", str(exc))
        return match.group(1).split(".")[0] if match else ""

    def _install_python_package(self, package: str) -> bool:
        package = str(package or "").strip()
        if not package:
            return False
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", package],
            capture_output=True,
            text=True,
            timeout=max(120, int(getattr(self.policy, "command_timeout_seconds", 120) or 120)),
            check=False,
        )
        return proc.returncode == 0
