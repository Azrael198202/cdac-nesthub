from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from ai_core.runtime.environment import RuntimeCommandExecutor, RuntimePermissionPolicy


class RuntimeCommandService:
    """Unified command service for generated runtime tools.

    Supports shell commands, Python module commands, and direct executable
    commands through the same permission policy. The default policy allows local
    self-healing and can be downgraded by runtime configuration later.
    """

    def __init__(self, *, policy: RuntimePermissionPolicy | None = None) -> None:
        self.executor = RuntimeCommandExecutor(policy=policy or RuntimePermissionPolicy.from_env())

    async def run_shell(self, command: str, *, timeout_seconds: int = 300, cwd: str | Path | None = None) -> dict[str, Any]:
        return (await self.executor.run_shell(command, timeout_seconds=timeout_seconds, cwd=cwd, kind="shell")).to_dict()

    async def run_command(self, args: Sequence[str], *, timeout_seconds: int = 300, cwd: str | Path | None = None) -> dict[str, Any]:
        return (await self.executor.run_exec(args, timeout_seconds=timeout_seconds, cwd=cwd, kind="command")).to_dict()

    async def run_python_module(self, module: str, args: Sequence[str] = (), *, timeout_seconds: int = 300) -> dict[str, Any]:
        return (await self.executor.run_python_module(module, args, timeout_seconds=timeout_seconds)).to_dict()
