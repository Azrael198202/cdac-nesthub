from __future__ import annotations

import json
import shutil
import os
import urllib.request
import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_core.utils.safe_subprocess import run_text
from ai_core.config.paths import RUNTIME_DOWNLOADS, RUNTIME_EXTERNAL_RUNTIMES
from auxiliary_brain.runtime.external_runtimes.gguf_model_resolver import GGUFModelResolver
from auxiliary_brain.runtime.observability.runtime_console import emit_console_event


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
    - ollama_gguf: downloads/stages a GGUF and imports it with `ollama create`.
    - huggingface_snapshot: uses huggingface_hub if installed.

    The class is intentionally generic and does not decide business suitability.
    It only stages a model candidate under runtime/downloads/models and returns
    whether benchmark may continue.
    """

    def __init__(self) -> None:
        self.root = RUNTIME_EXTERNAL_RUNTIMES / "models"
        self.root.mkdir(parents=True, exist_ok=True)
        self.gguf_resolver = GGUFModelResolver(self.root)

    def download(self, candidate: dict[str, Any], *, approved: bool = False, timeout_seconds: int = 3600) -> dict[str, Any]:
        model_id = str(candidate.get("model_id") or candidate.get("id") or candidate.get("name") or "").strip()
        emit_console_event(area="model_downloader", event="prepare_requested", status="running", message=f"prepare model {model_id or 'unknown'}", data={"model_id": model_id, "candidate_runtime": candidate.get("runtime"), "timeout_seconds": timeout_seconds})
        if not model_id:
            return self._result("failed", "unknown", "unknown", None, None, False, True, "No model id was provided.", {})
        strategy = candidate.get("download_strategy") if isinstance(candidate.get("download_strategy"), dict) else {}
        runtime = str(candidate.get("runtime") or strategy.get("preferred_runtime") or self._infer_runtime(model_id, candidate))
        review_needed = bool(candidate.get("requires_human_review") or candidate.get("license_review_required"))
        if review_needed and not approved:
            return self._result("approval_required", model_id, runtime, None, None, False, True, "Model download requires human approval.", {"candidate": candidate})

        resolved_candidate = self.gguf_resolver.resolve_candidate({**candidate, "model_id": model_id})
        resolved_runtime = str(resolved_candidate.get("runtime") or runtime)
        if resolved_runtime == "ollama_gguf" or self._candidate_has_gguf(resolved_candidate):
            return self._prepare_ollama_gguf(model_id, resolved_candidate, timeout_seconds=timeout_seconds)
        if runtime == "ollama" or ":" in model_id and not "/" in model_id:
            return self._download_ollama(model_id, resolved_candidate, timeout_seconds=timeout_seconds)
        return self._download_huggingface(model_id, candidate, timeout_seconds=timeout_seconds)


    def _candidate_has_gguf(self, candidate: dict[str, Any]) -> bool:
        for key in ("gguf_url", "gguf_path", "local_path", "source_url"):
            value = str(candidate.get(key) or "")
            if value.lower().endswith(".gguf") or ".gguf" in value.lower():
                return True
        return False

    def _prepare_ollama_gguf(self, model_id: str, candidate: dict[str, Any], *, timeout_seconds: int) -> dict[str, Any]:
        exe = shutil.which("ollama")
        if not exe:
            return self._result("unavailable", model_id, "ollama_gguf", None, None, False, True, "ollama command is not available.", {"candidate": candidate})
        try:
            gguf = self._resolve_or_download_gguf(model_id, candidate, timeout_seconds=timeout_seconds)
            expected = str(candidate.get("sha256") or "").strip()
            if expected and not self._sha256_ok(gguf, expected):
                return self._result("failed", model_id, "ollama_gguf", str(gguf), None, False, True, "GGUF checksum mismatch.", {"candidate": candidate})
            work = self.root / "ollama_imports" / self._safe(model_id)
            work.mkdir(parents=True, exist_ok=True)
            modelfile = work / "Modelfile"
            params = candidate.get("parameters") if isinstance(candidate.get("parameters"), dict) else {}
            lines = [f"FROM {gguf.resolve().as_posix()}"]
            for key, value in params.items():
                if key and value is not None:
                    lines.append(f"PARAMETER {key} {value}")
            modelfile.write_text("\n".join(lines) + "\n", encoding="utf-8")
            cmd = [exe, "create", model_id, "-f", str(modelfile)]
            emit_console_event(area="model_downloader", event="ollama_gguf_import_start", status="running", message="ollama create from GGUF", data={"model_id": model_id, "gguf": str(gguf), "modelfile": str(modelfile), "command": cmd})
            proc = run_text(cmd, text=True, capture_output=True, timeout=timeout_seconds)
            ok = proc.returncode == 0
            emit_console_event(area="model_downloader", event="ollama_gguf_import_end", status="completed" if ok else "failed", message="GGUF import completed" if ok else "GGUF import failed", data={"model_id": model_id, "returncode": proc.returncode, "stderr_tail": proc.stderr[-2000:], "stdout_tail": proc.stdout[-2000:]})
            return self._result(
                "downloaded" if ok else "failed",
                model_id,
                "ollama_gguf",
                str(gguf),
                cmd,
                ok,
                not ok,
                "GGUF model imported into Ollama." if ok else "Ollama GGUF import failed.",
                {"stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:], "modelfile": str(modelfile), "candidate": candidate},
            )
        except Exception as exc:
            return self._result("failed", model_id, "ollama_gguf", None, None, False, True, str(exc), {"candidate": candidate})

    def _resolve_or_download_gguf(self, model_id: str, candidate: dict[str, Any], *, timeout_seconds: int) -> Path:
        local = os.environ.get(str(candidate.get("local_path_env") or "")) if candidate.get("local_path_env") else None
        local = local or str(candidate.get("gguf_path") or candidate.get("local_path") or "").strip()
        if local:
            path = Path(local).expanduser()
            if path.exists():
                return path
        url = os.environ.get(str(candidate.get("url_env") or "")) if candidate.get("url_env") else None
        url = url or str(candidate.get("gguf_url") or candidate.get("source_url") or "").strip()
        if not url:
            raise RuntimeError("No GGUF local path or URL was provided.")
        target_dir = self.root / self._safe(model_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = str(candidate.get("filename") or url.rsplit("/", 1)[-1] or (self._safe(model_id) + ".gguf"))
        if not filename.lower().endswith(".gguf"):
            filename += ".gguf"
        target = target_dir / self._safe(filename)
        if target.exists() and target.stat().st_size > 0:
            return target
        req = urllib.request.Request(url, headers={"User-Agent": "ai-core-model-downloader/1.0"})
        tmp = target.with_suffix(target.suffix + ".part")
        with urllib.request.urlopen(req, timeout=timeout_seconds) as response, tmp.open("wb") as fh:
            shutil.copyfileobj(response, fh)
        tmp.replace(target)
        return target

    def _sha256_ok(self, path: Path, expected: str) -> bool:
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest().lower() == expected.lower()

    def _download_ollama(self, model_id: str, candidate: dict[str, Any], *, timeout_seconds: int) -> dict[str, Any]:
        exe = shutil.which("ollama")
        if not exe:
            return self._result("unavailable", model_id, "ollama", None, None, False, True, "ollama command is not available.", {"candidate": candidate})
        cmd = [exe, "pull", model_id]
        try:
            emit_console_event(area="model_downloader", event="ollama_pull_start", status="running", message="ollama pull started", data={"model_id": model_id, "command": cmd, "timeout_seconds": timeout_seconds})
            proc = run_text(cmd, text=True, capture_output=True, timeout=timeout_seconds)
            ok = proc.returncode == 0
            emit_console_event(area="model_downloader", event="ollama_pull_end", status="completed" if ok else "failed", message="Ollama pull completed" if ok else "Ollama pull failed", data={"model_id": model_id, "returncode": proc.returncode, "stderr_tail": proc.stderr[-2000:], "stdout_tail": proc.stdout[-2000:]})
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
        emit_console_event(area="model_downloader", event="prepare_result", status=status, message=reason, data={"model_id": model_id, "runtime": runtime, "local_path": local_path, "command": command, "metadata_path": str(meta_path), "ready_for_benchmark": ready})
        return asdict(ModelDownloadResult(status, model_id, runtime, local_path, command, str(meta_path), ready, review, reason))
