from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_TRACES


@dataclass
class ModelBenchmarkResult:
    status: str
    model_id: str
    runtime: str
    metrics: dict[str, Any]
    passed: bool
    report_path: str
    reason: str


class RuntimeModelBenchmark:
    """Run a minimal benchmark before model route registration.

    This benchmark is deliberately small and generic. It checks whether a model
    can respond within timeout and whether output is non-empty. Task-specific
    benchmark suites can be generated later under runtime/generated.
    """

    def __init__(self) -> None:
        self.root = RUNTIME_TRACES / "model_benchmarks"
        self.root.mkdir(parents=True, exist_ok=True)

    def benchmark(self, *, model_id: str, runtime: str, prompt: str = "Return one valid JSON object: {\"ok\": true}", timeout_seconds: int = 120) -> dict[str, Any]:
        start = time.time()
        if runtime == "ollama":
            result = self._bench_ollama(model_id, prompt, timeout_seconds=timeout_seconds)
        else:
            result = {
                "status": "manual_benchmark_required",
                "stdout": "",
                "stderr": "Runtime-specific benchmark adapter is not configured.",
                "returncode": -1,
            }
        elapsed = time.time() - start
        stdout = str(result.get("stdout") or "")
        passed = result.get("returncode") == 0 and bool(stdout.strip())
        metrics = {
            "elapsed_seconds": round(elapsed, 3),
            "stdout_chars": len(stdout),
            "stderr_chars": len(str(result.get("stderr") or "")),
            "returncode": result.get("returncode"),
            "raw_status": result.get("status"),
        }
        report = {
            "model_id": model_id,
            "runtime": runtime,
            "metrics": metrics,
            "passed": passed,
            "sample_output_preview": stdout[:2000],
            "stderr_preview": str(result.get("stderr") or "")[-2000:],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        path = self.root / f"{self._safe(model_id)}.{int(time.time())}.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return asdict(ModelBenchmarkResult(
            status="passed" if passed else "failed",
            model_id=model_id,
            runtime=runtime,
            metrics=metrics,
            passed=passed,
            report_path=str(path),
            reason="Benchmark passed." if passed else "Benchmark failed or requires a runtime-specific adapter.",
        ))

    def _bench_ollama(self, model_id: str, prompt: str, *, timeout_seconds: int) -> dict[str, Any]:
        exe = shutil.which("ollama")
        if not exe:
            return {"status": "unavailable", "returncode": -1, "stdout": "", "stderr": "ollama command is not available."}
        try:
            proc = subprocess.run([exe, "run", model_id, prompt], text=True, capture_output=True, timeout=timeout_seconds)
            return {"status": "completed", "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
        except Exception as exc:
            return {"status": "failed", "returncode": -1, "stdout": "", "stderr": str(exc)}

    def _safe(self, value: str) -> str:
        return "".join(c if c.isalnum() or c in {"_", "-", "."} else "_" for c in value)[:160] or "model"
