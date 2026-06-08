from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from ai_core.config.paths import RUNTIME_GENERATED, RUNTIME_TRACES, RUNTIME_DIR
from evidence_engine.contracts import EvidenceItem, EvidencePackage, EvidenceRequest, safe_read_lines


class RuntimeEvidenceCollector:
    """Collect filtered runtime evidence before any model-based analysis.

    This keeps small local models away from huge raw log folders. The collector
    is deterministic and only uses structural identifiers such as run_id,
    task_name, participant_id, and event_name.
    """

    def __init__(self, *, roots: Iterable[Path] | None = None) -> None:
        self.roots = list(roots or [RUNTIME_TRACES, RUNTIME_GENERATED, RUNTIME_DIR / "logs"])

    def collect(self, request: EvidenceRequest) -> EvidencePackage:
        package = EvidencePackage(request=request)
        tokens = [
            request.run_id,
            request.task_name,
            request.participant_id,
            request.event_name,
        ]
        tokens = [str(token).strip() for token in tokens if str(token).strip()]
        for path in self._candidate_files(tokens):
            lines = safe_read_lines(path, max_lines=max(20, request.max_lines_per_file))
            matched_lines = self._filter_lines(lines, tokens)
            if not matched_lines and tokens:
                continue
            item = EvidenceItem(
                source=str(path),
                kind=self._kind(path),
                matched=bool(matched_lines),
                lines=matched_lines or lines[-min(len(lines), 30):],
                metadata={"line_count": len(lines)},
            )
            package.add_item(item)
        package.summary = {
            "item_count": len(package.items),
            "matched_item_count": sum(1 for item in package.items if item.matched),
            "tokens": tokens,
        }
        return package

    def _candidate_files(self, tokens: list[str]) -> list[Path]:
        files: list[Path] = []
        suffixes = {".json", ".jsonl", ".log", ".txt"}
        for root in self.roots:
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix not in suffixes:
                    continue
                name_hit = any(token in path.name or token in str(path.parent) for token in tokens)
                if name_hit or not tokens:
                    files.append(path)
        # If exact filename matching found little, include common trace files so
        # line filtering can still find evidence.
        if len(files) < 5 and tokens:
            common_names = {"runtime_console.jsonl", "scheduler.jsonl", "service_lifecycle.jsonl"}
            for root in self.roots:
                if root.exists():
                    for path in root.rglob("*"):
                        if path.is_file() and (path.name in common_names or path.suffix == ".jsonl"):
                            files.append(path)
        unique: dict[str, Path] = {str(path): path for path in files}
        return sorted(unique.values(), key=lambda p: str(p))[:80]

    def _filter_lines(self, lines: list[str], tokens: list[str]) -> list[str]:
        if not tokens:
            return lines[-60:]
        out: list[str] = []
        lowered_tokens = [token.casefold() for token in tokens]
        for line in lines:
            lowered = line.casefold()
            if any(token in lowered for token in lowered_tokens):
                out.append(line)
        return out[-200:]

    def _kind(self, path: Path) -> str:
        if path.suffix == ".jsonl":
            return "event_log"
        if path.suffix == ".json":
            return "artifact"
        if path.suffix == ".log":
            return "runtime_log"
        return "text"

    def write_package(self, package: EvidencePackage, *, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(package.to_dict(), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return output_path
