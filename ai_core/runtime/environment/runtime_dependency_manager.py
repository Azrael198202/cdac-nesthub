from __future__ import annotations

import importlib.util
import json
import os
import platform
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_TRACES
from ai_core.utils.safe_json import safe_json_dumps

from .permission_policy import RuntimePermissionPolicy
from .runtime_command_executor import RuntimeCommandExecutor, RuntimeCommandResult


@dataclass
class RuntimeDependencyResult:
    dependency_id: str
    status: str
    changed: bool = False
    attempts: list[dict[str, Any]] = field(default_factory=list)
    message: str = ""
    trace_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RuntimeDependencyManager:
    """Generic runtime dependency self-healing manager.

    Responsibilities:
    - Detect missing Python packages, CLI commands, and browser runtimes.
    - Run repair commands under a configurable permission policy.
    - Record all checks and repairs into trace files.

    It deliberately avoids domain/task keywords. Capabilities can request a
    generic dependency id; the manager decides how to verify and repair it.
    """

    def __init__(self, *, policy: RuntimePermissionPolicy | None = None, run_id: str = "") -> None:
        self.policy = policy or RuntimePermissionPolicy.from_env()
        self.runner = RuntimeCommandExecutor(policy=self.policy)
        self.run_id = run_id or "runtime"

    async def ensure(self, dependency_id: str, *, context: dict[str, Any] | None = None) -> RuntimeDependencyResult:
        dependency_id = str(dependency_id or "").strip()
        context = context or {}
        trace_path = self._trace_path(dependency_id)
        result = RuntimeDependencyResult(dependency_id=dependency_id, status="unknown", trace_path=str(trace_path))
        self._record(trace_path, "start", {"dependency_id": dependency_id, "context": context, "policy": self.policy.to_dict()})

        if dependency_id in {"playwright_browser", "browser_runtime", "browser_network_observer"}:
            result = await self._ensure_playwright_browser(trace_path=trace_path, dependency_id=dependency_id)
        elif dependency_id.startswith("python:"):
            pkg = dependency_id.split(":", 1)[1]
            result = await self._ensure_python_package(pkg, trace_path=trace_path, dependency_id=dependency_id)
        elif dependency_id.startswith("command:"):
            cmd = dependency_id.split(":", 1)[1]
            result = await self._ensure_command(cmd, trace_path=trace_path, dependency_id=dependency_id)
        else:
            result.status = "unsupported_dependency_id"
            result.message = f"No generic installer is registered for {dependency_id}"

        result.trace_path = str(trace_path)
        self._record(trace_path, "finish", result.to_dict())
        return result

    async def _ensure_python_package(self, package: str, *, trace_path: Path, dependency_id: str) -> RuntimeDependencyResult:
        result = RuntimeDependencyResult(dependency_id=dependency_id, status="unknown")
        module_name = package.replace("-", "_")
        if importlib.util.find_spec(module_name) is not None:
            result.status = "ready"
            result.message = "python_package_importable"
            return result
        if not self.policy.can_execute(kind="install"):
            result.status = "blocked"
            result.message = "install_blocked_by_policy"
            return result
        cmd = [sys.executable, "-m", "pip", "install", package]
        attempt = await self.runner.run_exec(cmd, timeout_seconds=self.policy.command_timeout_seconds, kind="install")
        result.attempts.append(attempt.to_dict())
        self._record(trace_path, "install_python_package", attempt.to_dict())
        importlib.invalidate_caches()
        result.changed = attempt.returncode == 0
        result.status = "ready" if importlib.util.find_spec(module_name) is not None else "failed"
        result.message = "python_package_installed" if result.status == "ready" else "python_package_install_failed"
        return result

    async def _ensure_command(self, command: str, *, trace_path: Path, dependency_id: str) -> RuntimeDependencyResult:
        result = RuntimeDependencyResult(dependency_id=dependency_id, status="unknown")
        check = await self.runner.run_shell(self._which_command(command), timeout_seconds=30, kind="shell")
        result.attempts.append(check.to_dict())
        self._record(trace_path, "check_command", check.to_dict())
        result.status = "ready" if check.returncode == 0 else "missing"
        result.message = "command_found" if result.status == "ready" else "command_missing_no_generic_installer"
        return result

    async def _ensure_playwright_browser(self, *, trace_path: Path, dependency_id: str) -> RuntimeDependencyResult:
        result = RuntimeDependencyResult(dependency_id=dependency_id, status="unknown")

        # 1) Ensure the Python package is importable.
        if importlib.util.find_spec("playwright") is None:
            package_result = await self._ensure_python_package("playwright", trace_path=trace_path, dependency_id="python:playwright")
            result.attempts.extend(package_result.attempts)
            if package_result.status != "ready":
                result.status = "failed"
                result.message = "playwright_python_package_not_ready"
                return result
            result.changed = True

        # 2) Check whether a Chromium browser can be launched.
        check = await self.runner.run_exec(
            [sys.executable, "-c", self._playwright_launch_check_code()],
            timeout_seconds=60,
            kind="python",
        )
        result.attempts.append(check.to_dict())
        self._record(trace_path, "check_playwright_browser", check.to_dict())
        if check.returncode == 0:
            result.status = "ready"
            result.message = "playwright_browser_ready"
            return result

        if not self.policy.can_execute(kind="install"):
            result.status = "blocked"
            result.message = "browser_install_blocked_by_policy"
            return result

        # 3) Install browser binaries. This is intentionally generic browser
        # runtime repair, not task-specific logic.
        install = await self.runner.run_exec(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            timeout_seconds=max(600, self.policy.command_timeout_seconds),
            kind="install",
        )
        result.attempts.append(install.to_dict())
        self._record(trace_path, "install_playwright_chromium", install.to_dict())
        if install.returncode == 0:
            result.changed = True

        # 4) If browser binary exists but OS dependencies are missing, try the
        # official dependency installer when the permission policy allows it.
        verify_after_install = await self.runner.run_exec(
            [sys.executable, "-c", self._playwright_launch_check_code()],
            timeout_seconds=60,
            kind="python",
        )
        result.attempts.append(verify_after_install.to_dict())
        self._record(trace_path, "verify_playwright_after_install", verify_after_install.to_dict())
        if verify_after_install.returncode == 0:
            result.status = "ready"
            result.message = "playwright_browser_installed"
            return result

        if self.policy.can_execute(kind="system_install") and platform.system().lower() == "linux":
            with_deps = await self.runner.run_exec(
                [sys.executable, "-m", "playwright", "install", "--with-deps", "chromium"],
                timeout_seconds=max(900, self.policy.command_timeout_seconds),
                kind="system_install",
            )
            result.attempts.append(with_deps.to_dict())
            self._record(trace_path, "install_playwright_system_deps", with_deps.to_dict())
            if with_deps.returncode == 0:
                result.changed = True
            final_check = await self.runner.run_exec(
                [sys.executable, "-c", self._playwright_launch_check_code()],
                timeout_seconds=60,
                kind="python",
            )
            result.attempts.append(final_check.to_dict())
            self._record(trace_path, "final_playwright_check", final_check.to_dict())
            if final_check.returncode == 0:
                result.status = "ready"
                result.message = "playwright_browser_and_deps_ready"
                return result

        result.status = "failed"
        result.message = "playwright_browser_repair_failed"
        return result

    def _trace_path(self, dependency_id: str) -> Path:
        safe_id = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in dependency_id)[:80]
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        path = RUNTIME_TRACES / "dependency_recovery" / self.run_id / f"{ts}_{safe_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _record(self, path: Path, stage: str, data: dict[str, Any]) -> None:
        event = {
            "at": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "data": data,
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(safe_json_dumps(event) + "\n")

    def _which_command(self, command: str) -> str:
        if platform.system().lower() == "windows":
            return f"where {command}"
        return f"command -v {command}"

    def _playwright_launch_check_code(self) -> str:
        return (
            "import asyncio\n"
            "from playwright.async_api import async_playwright\n"
            "async def main():\n"
            "    async with async_playwright() as p:\n"
            "        browser = await p.chromium.launch(headless=True)\n"
            "        await browser.close()\n"
            "asyncio.run(main())\n"
        )
