from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ai_core.config.paths import RUNTIME_DOWNLOADS
from ai_core.security.dependency_scanner import DependencyScanner
from ai_core.security.repository_dependency_gate import RepositoryDependencyGate


@dataclass
class RepositoryAnalysisResult:
    status: str
    repository_url: str
    local_path: str | None
    metadata: dict[str, Any]
    readme_summary: dict[str, Any]
    license_summary: dict[str, Any]
    dependency_scan: dict[str, Any]
    safe_to_use_as_evidence: bool
    safe_to_execute: bool
    requires_human_review: bool
    reason: str


class GitHubRepositoryAnalyzer:
    """Clone and analyze external repositories as untrusted runtime evidence.

    The analyzer never executes repository code. It only performs a shallow clone
    into runtime/downloads, reads common metadata files, scans dependency files,
    and returns a conservative safety assessment for the runtime planner.
    """

    def __init__(self) -> None:
        self.download_root = RUNTIME_DOWNLOADS / "repositories"
        self.download_root.mkdir(parents=True, exist_ok=True)
        self.dependency_scanner = DependencyScanner()
        self.dependency_gate = RepositoryDependencyGate()

    def analyze(self, repository_url: str, *, request_id: str | None = None, timeout_seconds: int = 90) -> dict[str, Any]:
        if not self._is_allowed_repository_url(repository_url):
            return asdict(RepositoryAnalysisResult(
                status="blocked",
                repository_url=repository_url,
                local_path=None,
                metadata={},
                readme_summary={},
                license_summary={},
                dependency_scan={},
                safe_to_use_as_evidence=False,
                safe_to_execute=False,
                requires_human_review=True,
                reason="Repository URL is not allowed for automatic clone.",
            ))
        git = shutil.which("git")
        if not git:
            return asdict(RepositoryAnalysisResult(
                status="unavailable",
                repository_url=repository_url,
                local_path=None,
                metadata={},
                readme_summary={},
                license_summary={},
                dependency_scan={},
                safe_to_use_as_evidence=False,
                safe_to_execute=False,
                requires_human_review=True,
                reason="git command is not available.",
            ))
        target = self._target_path(repository_url, request_id=request_id)
        if target.exists():
            shutil.rmtree(target)
        proc = subprocess.run(
            [git, "clone", "--depth", "1", "--filter=blob:limit=1m", repository_url, str(target)],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        if proc.returncode != 0:
            return asdict(RepositoryAnalysisResult(
                status="clone_failed",
                repository_url=repository_url,
                local_path=None,
                metadata={"stderr": proc.stderr[-2000:]},
                readme_summary={},
                license_summary={},
                dependency_scan={},
                safe_to_use_as_evidence=False,
                safe_to_execute=False,
                requires_human_review=True,
                reason="Repository clone failed.",
            ))
        readme_summary = self._read_text_summary(target, ["README.md", "README.rst", "README.txt", "README"])
        license_summary = self._read_text_summary(target, ["LICENSE", "LICENSE.md", "COPYING", "NOTICE"])
        dep_scan = self.dependency_scanner.scan_path(target)
        dependency_gate = self.dependency_gate.evaluate(target, approved=False)
        metadata = {
            "cloned_at": datetime.now(timezone.utc).isoformat(),
            "file_count": self._count_files(target),
            "top_level_files": sorted([p.name for p in target.iterdir()])[:50],
        }
        requires_review = not bool(license_summary.get("present")) or bool(dep_scan.get("requires_human_review"))
        return asdict(RepositoryAnalysisResult(
            status="analyzed",
            repository_url=repository_url,
            local_path=str(target),
            metadata=metadata,
            readme_summary=readme_summary,
            license_summary=license_summary,
            dependency_scan={**dep_scan, "install_gate": dependency_gate},
            safe_to_use_as_evidence=True,
            safe_to_execute=False,
            requires_human_review=requires_review,
            reason="Repository cloned and analyzed as evidence. Code execution is not automatically allowed.",
        ))

    def _is_allowed_repository_url(self, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.scheme in {"https", "http"} and parsed.netloc.lower() in {"github.com", "www.github.com"}

    def _target_path(self, url: str, *, request_id: str | None) -> Path:
        parsed = urlparse(url)
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        name = "_".join(parts[:2]) or "repository"
        safe = "".join(c if c.isalnum() or c in {"_", "-"} else "_" for c in name)
        prefix = request_id or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return self.download_root / f"{prefix}_{safe}"

    def _read_text_summary(self, root: Path, names: list[str]) -> dict[str, Any]:
        for name in names:
            path = root / name
            if path.exists() and path.is_file():
                text = path.read_text(encoding="utf-8", errors="ignore")
                return {"present": True, "path": str(path), "chars": len(text), "preview": text[:4000]}
        return {"present": False}

    def _count_files(self, root: Path) -> int:
        count = 0
        for path in root.rglob("*"):
            if ".git" in path.parts:
                continue
            if path.is_file():
                count += 1
        return count
