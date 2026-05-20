from __future__ import annotations

import os
from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class RuntimePermissionPolicy:
    """Generic runtime permission policy for self-healing execution.

    Default mode is intentionally high privilege for local development, as the
    runtime is expected to repair missing dependencies without asking the user.
    Future deployments can lower the level through environment variables or a
    generated runtime config without changing core code.
    """

    level: str = "administrator"
    allow_shell: bool = True
    allow_python: bool = True
    allow_install: bool = True
    allow_system_package_install: bool = True
    allow_network_install: bool = True
    require_human_approval: bool = False
    command_timeout_seconds: int = 900

    @classmethod
    def from_env(cls) -> "RuntimePermissionPolicy":
        level = os.environ.get("AI_CORE_RUNTIME_PERMISSION_LEVEL", "administrator").strip() or "administrator"
        def flag(name: str, default: bool) -> bool:
            raw = os.environ.get(name)
            if raw is None:
                return default
            return raw.strip().lower() not in {"0", "false", "no", "off"}
        return cls(
            level=level,
            allow_shell=flag("AI_CORE_ALLOW_SHELL", True),
            allow_python=flag("AI_CORE_ALLOW_PYTHON", True),
            allow_install=flag("AI_CORE_ALLOW_INSTALL", True),
            allow_system_package_install=flag("AI_CORE_ALLOW_SYSTEM_INSTALL", True),
            allow_network_install=flag("AI_CORE_ALLOW_NETWORK_INSTALL", True),
            require_human_approval=flag("AI_CORE_REQUIRE_INSTALL_APPROVAL", False),
            command_timeout_seconds=int(os.environ.get("AI_CORE_COMMAND_TIMEOUT_SECONDS", "900") or "900"),
        )

    def can_execute(self, *, kind: str) -> bool:
        kind = str(kind or "").strip().lower()
        if kind in {"shell", "command", "cli"}:
            return self.allow_shell
        if kind in {"python", "py"}:
            return self.allow_python
        if kind in {"install", "package_install", "runtime_install"}:
            return self.allow_install and self.allow_network_install
        if kind in {"system_install", "os_package_install"}:
            return self.allow_install and self.allow_system_package_install
        return True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
