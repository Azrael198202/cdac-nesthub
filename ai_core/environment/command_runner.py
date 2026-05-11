from __future__ import annotations
import subprocess
from dataclasses import dataclass


@dataclass
class CommandResult:
    command: str
    returncode: int
    stdout: str
    stderr: str


class CommandRunner:
    def run(self, command: str, timeout: int = 1800) -> CommandResult:
        proc = subprocess.run(
            command,
            shell=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        return CommandResult(command, proc.returncode, proc.stdout, proc.stderr)
