from __future__ import annotations

from typing import Any
from ai_core.utils.safe_subprocess import run_text


class ShellRuntimeExecutor:
    """Executes shell commands with timeout and captured output."""

    def run(self, command: list[str], *, timeout_seconds: int = 10, cwd: str | None = None) -> dict[str, Any]:
        proc = run_text(command, cwd=cwd, capture_output=True, text=True, timeout=timeout_seconds)
        return {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
