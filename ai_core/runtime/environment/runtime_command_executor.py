from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Sequence

from .permission_policy import RuntimePermissionPolicy


@dataclass
class RuntimeCommandResult:
    command: list[str] | str
    returncode: int
    stdout: str = ""
    stderr: str = ""
    cwd: str = ""
    timeout: bool = False
    skipped: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if len(data.get("stdout") or "") > 12000:
            data["stdout"] = data["stdout"][:12000] + " ...[truncated]"
        if len(data.get("stderr") or "") > 12000:
            data["stderr"] = data["stderr"][:12000] + " ...[truncated]"
        return data


class RuntimeCommandExecutor:
    """Async shell/Python command runner used by runtime self-healing.

    This executor is generic and does not know any business capability. It is a
    controlled gateway for generated tools and dependency repair commands.
    """

    def __init__(self, *, policy: RuntimePermissionPolicy | None = None) -> None:
        self.policy = policy or RuntimePermissionPolicy.from_env()

    async def run_exec(
        self,
        args: Sequence[str],
        *,
        timeout_seconds: int | None = None,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        kind: str = "command",
    ) -> RuntimeCommandResult:
        if not self.policy.can_execute(kind=kind):
            return RuntimeCommandResult(command=list(args), returncode=126, skipped=True, reason=f"blocked_by_policy:{kind}")
        timeout = timeout_seconds or self.policy.command_timeout_seconds
        proc_env = os.environ.copy()
        if env:
            proc_env.update({str(k): str(v) for k, v in env.items()})
        try:
            proc = await asyncio.create_subprocess_exec(
                *[str(a) for a in args],
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd) if cwd else None,
                env=proc_env,
            )
            try:
                out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                return RuntimeCommandResult(command=list(args), returncode=124, timeout=True, cwd=str(cwd or ""), reason="timeout")
            return RuntimeCommandResult(
                command=list(args),
                returncode=int(proc.returncode or 0),
                stdout=out.decode("utf-8", errors="replace") if out else "",
                stderr=err.decode("utf-8", errors="replace") if err else "",
                cwd=str(cwd or ""),
            )
        except FileNotFoundError as exc:
            return RuntimeCommandResult(command=list(args), returncode=127, stderr=str(exc), cwd=str(cwd or ""), reason="command_not_found")
        except Exception as exc:
            return RuntimeCommandResult(command=list(args), returncode=1, stderr=str(exc), cwd=str(cwd or ""), reason="command_error")

    async def run_shell(
        self,
        command: str,
        *,
        timeout_seconds: int | None = None,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        kind: str = "shell",
    ) -> RuntimeCommandResult:
        if not self.policy.can_execute(kind=kind):
            return RuntimeCommandResult(command=command, returncode=126, skipped=True, reason=f"blocked_by_policy:{kind}")
        timeout = timeout_seconds or self.policy.command_timeout_seconds
        proc_env = os.environ.copy()
        if env:
            proc_env.update({str(k): str(v) for k, v in env.items()})
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd) if cwd else None,
                env=proc_env,
            )
            try:
                out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                return RuntimeCommandResult(command=command, returncode=124, timeout=True, cwd=str(cwd or ""), reason="timeout")
            return RuntimeCommandResult(
                command=command,
                returncode=int(proc.returncode or 0),
                stdout=out.decode("utf-8", errors="replace") if out else "",
                stderr=err.decode("utf-8", errors="replace") if err else "",
                cwd=str(cwd or ""),
            )
        except Exception as exc:
            return RuntimeCommandResult(command=command, returncode=1, stderr=str(exc), cwd=str(cwd or ""), reason="shell_error")

    async def run_python_module(self, module: str, args: Sequence[str] = (), *, timeout_seconds: int | None = None) -> RuntimeCommandResult:
        return await self.run_exec([sys.executable, "-m", module, *[str(a) for a in args]], timeout_seconds=timeout_seconds, kind="python")
