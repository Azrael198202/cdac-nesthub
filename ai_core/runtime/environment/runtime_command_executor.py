from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Sequence

from .permission_policy import RuntimePermissionPolicy
from ai_core.runtime.state import runtime_state_manager


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
        run_id = str(env.get("AI_RUNTIME_STATE_RUN_ID") if isinstance(env, dict) else "") or str(os.getenv("AI_RUNTIME_STATE_RUN_ID") or "runtime_command")
        step_id = str(env.get("AI_RUNTIME_STATE_STEP_ID") if isinstance(env, dict) else "") or f"command.{kind}"
        runtime_state_manager.emit(
            run_id=run_id,
            step_id=step_id,
            level="advanced",
            kind="command",
            status="running",
            title="Command execution",
            message="Executing runtime command.",
            method="subprocess_exec",
            tool=" ".join(str(a) for a in list(args)[:3]),
            input={"args": [str(a) for a in args], "cwd": str(cwd or ""), "kind": kind},
            progress=5,
        )
        if not self.policy.can_execute(kind=kind):
            result = RuntimeCommandResult(command=list(args), returncode=126, skipped=True, reason=f"blocked_by_policy:{kind}")
            runtime_state_manager.emit(run_id=run_id, step_id=step_id, level="developer", kind="command", status="skipped", title="Command blocked", message=result.reason, output=result.to_dict(), progress=100)
            return result
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
                result = RuntimeCommandResult(command=list(args), returncode=124, timeout=True, cwd=str(cwd or ""), reason="timeout")
                runtime_state_manager.emit(run_id=run_id, step_id=step_id, level="developer", kind="command", status="failed", title="Command timeout", message="Runtime command timed out.", output=result.to_dict(), progress=100)
                return result
            result = RuntimeCommandResult(
                command=list(args),
                returncode=int(proc.returncode or 0),
                stdout=out.decode("utf-8", errors="replace") if out else "",
                stderr=err.decode("utf-8", errors="replace") if err else "",
                cwd=str(cwd or ""),
            )
            runtime_state_manager.emit(
                run_id=run_id,
                step_id=step_id,
                level="advanced",
                kind="command",
                status="completed" if result.returncode == 0 else "failed",
                title="Command completed",
                message=f"Command returncode={result.returncode}.",
                output=result.to_dict(),
                progress=100,
            )
            return result
        except FileNotFoundError as exc:
            result = RuntimeCommandResult(command=list(args), returncode=127, stderr=str(exc), cwd=str(cwd or ""), reason="command_not_found")
            runtime_state_manager.emit(run_id=run_id, step_id=step_id, level="developer", kind="command", status="failed", title="Command not found", message=str(exc), output=result.to_dict(), progress=100)
            return result
        except Exception as exc:
            result = RuntimeCommandResult(command=list(args), returncode=1, stderr=str(exc), cwd=str(cwd or ""), reason="command_error")
            runtime_state_manager.emit(run_id=run_id, step_id=step_id, level="developer", kind="command", status="failed", title="Command error", message=str(exc), output=result.to_dict(), progress=100)
            return result

    async def run_shell(
        self,
        command: str,
        *,
        timeout_seconds: int | None = None,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        kind: str = "shell",
    ) -> RuntimeCommandResult:
        run_id = str(env.get("AI_RUNTIME_STATE_RUN_ID") if isinstance(env, dict) else "") or str(os.getenv("AI_RUNTIME_STATE_RUN_ID") or "runtime_shell")
        step_id = str(env.get("AI_RUNTIME_STATE_STEP_ID") if isinstance(env, dict) else "") or f"shell.{kind}"
        runtime_state_manager.emit(run_id=run_id, step_id=step_id, level="advanced", kind="command", status="running", title="Shell execution", message="Executing runtime shell command.", method="subprocess_shell", tool=str(command).split()[0] if command else "shell", input={"command": command, "cwd": str(cwd or ""), "kind": kind}, progress=5)
        if not self.policy.can_execute(kind=kind):
            result = RuntimeCommandResult(command=command, returncode=126, skipped=True, reason=f"blocked_by_policy:{kind}")
            runtime_state_manager.emit(run_id=run_id, step_id=step_id, level="developer", kind="command", status="skipped", title="Shell blocked", message=result.reason, output=result.to_dict(), progress=100)
            return result
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
                result = RuntimeCommandResult(command=command, returncode=124, timeout=True, cwd=str(cwd or ""), reason="timeout")
                runtime_state_manager.emit(run_id=run_id, step_id=step_id, level="developer", kind="command", status="failed", title="Shell timeout", message="Runtime shell command timed out.", output=result.to_dict(), progress=100)
                return result
            result = RuntimeCommandResult(
                command=command,
                returncode=int(proc.returncode or 0),
                stdout=out.decode("utf-8", errors="replace") if out else "",
                stderr=err.decode("utf-8", errors="replace") if err else "",
                cwd=str(cwd or ""),
            )
            runtime_state_manager.emit(run_id=run_id, step_id=step_id, level="advanced", kind="command", status="completed" if result.returncode == 0 else "failed", title="Shell completed", message=f"Shell returncode={result.returncode}.", output=result.to_dict(), progress=100)
            return result
        except Exception as exc:
            result = RuntimeCommandResult(command=command, returncode=1, stderr=str(exc), cwd=str(cwd or ""), reason="shell_error")
            runtime_state_manager.emit(run_id=run_id, step_id=step_id, level="developer", kind="command", status="failed", title="Shell error", message=str(exc), output=result.to_dict(), progress=100)
            return result

    async def run_python_module(self, module: str, args: Sequence[str] = (), *, timeout_seconds: int | None = None) -> RuntimeCommandResult:
        return await self.run_exec([sys.executable, "-m", module, *[str(a) for a in args]], timeout_seconds=timeout_seconds, kind="python")
