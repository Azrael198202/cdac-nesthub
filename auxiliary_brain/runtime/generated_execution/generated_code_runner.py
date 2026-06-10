from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Any
from ai_core.utils.safe_subprocess import run_text


class GeneratedCodeRunner:
    """Runs generated Python code in a constrained temporary process."""

    def run_python(self, source: str, *, timeout_seconds: int = 10) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "generated_unit.py"
            path.write_text(source, encoding="utf-8")
            proc = run_text(
                [sys.executable, str(path)],
                cwd=td,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            return {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
