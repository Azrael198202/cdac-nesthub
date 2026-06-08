from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_EXTERNAL_RUNTIMES


@dataclass(frozen=True)
class GGUFModelSource:
    model_id: str
    filename: str
    repo_id: str | None = None
    direct_url: str | None = None
    sha256: str | None = None


class GGUFModelResolver:
    """Resolve and stage external GGUF model files.

    This component is runtime infrastructure. It does not decide task suitability
    and does not embed domain/business capability logic. It resolves model files
    by explicit configuration first, then by a small runtime asset registry, and
    finally by optional Hugging Face model-tree metadata lookup when enabled.
    """

    DEFAULT_SOURCES: dict[str, GGUFModelSource] = {
        "qwen3.5:2b-q4_k_m": GGUFModelSource(
            model_id="qwen3.5:2b-q4_k_m",
            repo_id="unsloth/Qwen3.5-2B-GGUF",
            filename="Qwen3.5-2B-Q4_K_M.gguf",
            sha256="aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223",
        ),
        "qwen3.5:4b-q4_k_m": GGUFModelSource(
            model_id="qwen3.5:4b-q4_k_m",
            repo_id="unsloth/Qwen3.5-4B-GGUF",
            filename="Qwen3.5-4B-Q4_K_M.gguf",
        ),
    }

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or (RUNTIME_EXTERNAL_RUNTIMES / "models")
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        model_id = str(candidate.get("model_id") or candidate.get("id") or "").strip()
        if not model_id:
            return dict(candidate)
        merged = dict(candidate)

        # Explicit local/URL configuration has highest priority.
        configured_path = self._configured_path(merged)
        if configured_path:
            merged.setdefault("runtime", "ollama_gguf")
            merged["gguf_path"] = str(configured_path)
            merged.setdefault("filename", configured_path.name)
            return merged
        configured_url = self._configured_url(merged)
        if configured_url:
            merged.setdefault("runtime", "ollama_gguf")
            merged["gguf_url"] = configured_url
            merged.setdefault("filename", self._filename_from_url(configured_url) or self._default_filename(model_id))
            return merged

        source = self._source_for(model_id, merged)
        if not source:
            return merged
        local = self.find_local_file(model_id, source.filename)
        merged.setdefault("runtime", "ollama_gguf")
        merged.setdefault("filename", source.filename)
        if source.sha256 and not merged.get("sha256"):
            merged["sha256"] = source.sha256
        if local:
            merged["gguf_path"] = str(local)
            return merged
        url = source.direct_url or self._hf_resolve_url(source.repo_id, source.filename)
        if url:
            merged["gguf_url"] = url
        return merged

    def find_local_file(self, model_id: str, filename: str | None = None) -> Path | None:
        safe = self._safe(model_id)
        candidates: list[Path] = []
        if filename:
            candidates.extend([
                self.root / safe / filename,
                self.root / filename,
                RUNTIME_EXTERNAL_RUNTIMES / "models" / safe / filename,
                RUNTIME_EXTERNAL_RUNTIMES / "models" / filename,
            ])
        # If a specific filename is not present, prefer Q4_K_M files before any
        # other GGUF in the model directory.
        dirs = [self.root / safe, self.root, RUNTIME_EXTERNAL_RUNTIMES / "models" / safe]
        for directory in dirs:
            if directory.exists():
                candidates.extend(sorted(directory.glob("*Q4_K_M*.gguf")))
                candidates.extend(sorted(directory.glob("*.gguf")))
        for path in candidates:
            try:
                if path.exists() and path.is_file() and path.stat().st_size > 0:
                    return path
            except Exception:
                pass
        return None

    def metadata(self, candidate: dict[str, Any]) -> dict[str, Any]:
        resolved = self.resolve_candidate(candidate)
        return {
            "model_id": resolved.get("model_id") or resolved.get("id"),
            "runtime": resolved.get("runtime"),
            "gguf_path": resolved.get("gguf_path"),
            "gguf_url": resolved.get("gguf_url"),
            "filename": resolved.get("filename"),
            "sha256": resolved.get("sha256"),
            "root": str(self.root),
        }

    def _source_for(self, model_id: str, candidate: dict[str, Any]) -> GGUFModelSource | None:
        if str(candidate.get("filename") or "").lower().endswith(".gguf"):
            return GGUFModelSource(
                model_id=model_id,
                filename=str(candidate.get("filename")),
                repo_id=str(candidate.get("repo_id") or "").strip() or None,
                direct_url=str(candidate.get("gguf_url") or candidate.get("source_url") or "").strip() or None,
                sha256=str(candidate.get("sha256") or "").strip() or None,
            )
        if model_id in self.DEFAULT_SOURCES:
            return self.DEFAULT_SOURCES[model_id]
        return None

    def _configured_path(self, candidate: dict[str, Any]) -> Path | None:
        keys = [candidate.get("local_path_env"), candidate.get("gguf_path_env")]
        model_id = str(candidate.get("model_id") or "")
        keys.extend(self._env_keys(model_id, suffix="GGUF_PATH"))
        for key in keys:
            if not key:
                continue
            value = os.environ.get(str(key))
            if value:
                path = Path(value).expanduser()
                if path.exists():
                    return path
        for value in [candidate.get("gguf_path"), candidate.get("local_path")]:
            if value:
                path = Path(str(value)).expanduser()
                if path.exists():
                    return path
        return None

    def _configured_url(self, candidate: dict[str, Any]) -> str | None:
        keys = [candidate.get("url_env"), candidate.get("gguf_url_env")]
        model_id = str(candidate.get("model_id") or "")
        keys.extend(self._env_keys(model_id, suffix="GGUF_URL"))
        for key in keys:
            if not key:
                continue
            value = os.environ.get(str(key))
            if value:
                return value.strip()
        for value in [candidate.get("gguf_url"), candidate.get("source_url")]:
            if value:
                return str(value).strip()
        return None

    def _env_keys(self, model_id: str, *, suffix: str) -> list[str]:
        normalized = re.sub(r"[^A-Za-z0-9]+", "_", model_id).strip("_").upper()
        keys = []
        if normalized:
            keys.append(f"AI_CORE_{normalized}_{suffix}")
        # Backward-compatible explicit names from previous releases.
        if model_id == "qwen3.5:2b-q4_k_m":
            keys.append(f"AI_CORE_QWEN35_2B_Q4_K_M_{suffix}")
        if model_id == "qwen3.5:4b-q4_k_m":
            keys.append(f"AI_CORE_QWEN35_4B_Q4_K_M_{suffix}")
        return keys

    def _hf_resolve_url(self, repo_id: str | None, filename: str) -> str | None:
        if not repo_id:
            return None
        quoted = "/".join(urllib.parse.quote(part) for part in repo_id.split("/"))
        return f"https://huggingface.co/{quoted}/resolve/main/{urllib.parse.quote(filename)}?download=true"

    def _filename_from_url(self, url: str) -> str | None:
        try:
            return Path(urllib.parse.urlparse(url).path).name or None
        except Exception:
            return None

    def _default_filename(self, model_id: str) -> str:
        source = self.DEFAULT_SOURCES.get(model_id)
        return source.filename if source else (self._safe(model_id) + ".gguf")

    def _safe(self, value: str) -> str:
        return "".join(c if c.isalnum() or c in {"_", "-", "."} else "_" for c in value)[:160] or "model"
