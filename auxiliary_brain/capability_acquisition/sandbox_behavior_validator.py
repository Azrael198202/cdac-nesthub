from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class SandboxBehaviorValidationResult:
    passed: bool
    status: str
    reason: str
    checks: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_behavior_smoke_test(tool_dir: str | Path, verification_input: Mapping[str, Any]) -> SandboxBehaviorValidationResult:
    tool_dir = Path(tool_dir)
    runner = tool_dir / "__behavior_smoke_runner.py"
    payload_text = json.dumps(dict(verification_input or {}), ensure_ascii=False)
    runner.write_text(
        "import json, sys\n"
        f"sys.path.insert(0, {str(tool_dir)!r})\n"
        "from tool import run\n"
        f"payload = json.loads({payload_text!r})\n"
        "result = run(payload)\n"
        "assert isinstance(result, dict), result\n"
        "print(json.dumps(result, ensure_ascii=False, default=str))\n",
        encoding="utf-8",
    )
    proc = subprocess.run([sys.executable, str(runner)], cwd=str(tool_dir), text=True, capture_output=True, timeout=30)
    check = {"name": "behavior_smoke_runner", "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr, "passed": proc.returncode == 0}
    return SandboxBehaviorValidationResult(proc.returncode == 0, "passed" if proc.returncode == 0 else "failed", "completed" if proc.returncode == 0 else "behavior_smoke_failed", [check])
