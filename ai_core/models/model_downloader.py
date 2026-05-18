from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_core.utils.safe_subprocess import run_text
from ai_core.config.paths import RUNTIME_DOWNLOADS


@dataclass
class ModelDownloadResult:
    status: str
    model_id: str
    runtime: str
    local_path: str | None
    command: list[str] | None
    metadata_path: str
    ready_for_benchmark: bool
    requires_human_review: bool
    reason: str


class RuntimeModelDownloader:
    """Download or prepare model candidates for benchmark.

    Supported generic runtimes:
    - ollama: pulls by model id using `ollama pull`.
    - huggingface_snapshot: uses huggingface_hub if installed.

    The class is intentionally generic and does not decide business suitability.
    It only stages a model candidate under runtime/downloads/models and returns
    whether benchmark may continue.
    """

    def __init__(self) -> None:
        self.root = RUNTIME_DOWNLOADS / "models"
        self.root.mkdir(parents=True, exist_ok=True)

    def download(self, candidate: dict[str, Any], *, approved: bool = False, timeout_seconds: int = 3600) -> dict[str, Any]:
        model_id = str(candidate.get("model_id") or candidate.get("id") or candidate.get("name") or "").strip()
        if not model_id:
            return self._result("failed", "unknown", "unknown", None, None, False, True, "No model id was provided.", {})
        strategy = candidate.get("download_strategy") if isinstance(candidate.get("download_strategy"), dict) else {}
        runtime = str(candidate.get("runtime") or strategy.get("preferred_runtime") or self._infer_runtime(model_id, candidate))
        review_needed = bool(candidate.get("requires_human_review") or candidate.get("license_review_required"))
        if review_needed and not approved:
            return self._result("approval_required", model_id, runtime, None, None, False, True, "Model download requires human approval.", {"candidate": candidate})

        if runtime == "ollama" or ":" in model_id and not "/" in model_id:
            return self._download_ollama(model_id, candidate, timeout_seconds=timeout_seconds)
        return self._download_huggingface(model_id, candidate, timeout_seconds=timeout_seconds)

    def _download_ollama(self, model_id: str, candidate: dict[str, Any], *, timeout_seconds: int) -> dict[str, Any]:
        exe = shutil.which("ollama")
        if not exe:
            return self._result("unavailable", model_id, "ollama", None, None, False, True, "ollama command is not available.", {"candidate": candidate})
        cmd = [exe, "pull", model_id]
        try:
            proc = run_text(cmd, text=True, capture_output=True, timeout=timeout_seconds)
            ok = proc.returncode == 0
            return self._result(
                "downloaded" if ok else "failed",
                model_id,
                "ollama",
                None,
                cmd,
                ok,
                not ok,
                "Ollama model is ready for benchmark." if ok else "Ollama model pull failed.",
                {"stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:], "candidate": candidate},
            )
        except Exception as exc:
            return self._result("failed", model_id, "ollama", None, cmd, False, True, str(exc), {"candidate": candidate})

    def _download_huggingface(self, model_id: str, candidate: dict[str, Any], *, timeout_seconds: int) -> dict[str, Any]:
        target = self.root / self._safe(model_id)
        try:
            from huggingface_hub import snapshot_download  # type: ignore
        except Exception:
            return self._result(
                "unavailable",
                model_id,
                "huggingface_snapshot",
                str(target),
                None,
                False,
                True,
                "huggingface_hub is not installed. Install after approval before downloading.",
                {"candidate": candidate},
            )
        try:
            local = snapshot_download(repo_id=model_id, local_dir=str(target), local_dir_use_symlinks=False)
            return self._result("downloaded", model_id, "huggingface_snapshot", local, None, True, False, "Model snapshot is ready for benchmark.", {"candidate": candidate})
        except Exception as exc:
            return self._result("failed", model_id, "huggingface_snapshot", str(target), None, False, True, str(exc), {"candidate": candidate})

    def _infer_runtime(self, model_id: str, candidate: dict[str, Any]) -> str:
        source = str(candidate.get("source") or "").lower()
        if source == "huggingface" or "/" in model_id:
            return "huggingface_snapshot"
        return "ollama"

    def _safe(self, value: str) -> str:
        return "".join(c if c.isalnum() or c in {"_", "-", "."} else "_" for c in value)[:160] or "model"

    def _result(self, status: str, model_id: str, runtime: str, local_path: str | None, command: list[str] | None, ready: bool, review: bool, reason: str, metadata: dict[str, Any]) -> dict[str, Any]:
        meta_path = self.root / f"{self._safe(model_id)}.download.json"
        payload = {
            "status": status,
            "model_id": model_id,
            "runtime": runtime,
            "local_path": local_path,
            "command": command,
            "ready_for_benchmark": ready,
            "requires_human_review": review,
            "reason": reason,
            "metadata": metadata,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return asdict(ModelDownloadResult(status, model_id, runtime, local_path, command, str(meta_path), ready, review, reason))
