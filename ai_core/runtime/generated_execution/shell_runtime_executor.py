from __future__ import annotations

import subprocess
from typing import Any


class ShellRuntimeExecutor:
    """Executes shell commands with timeout and captured output."""

    def run(self, command: list[str], *, timeout_seconds: int = 10, cwd: str | None = None) -> dict[str, Any]:
        proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout_seconds)
        return {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
