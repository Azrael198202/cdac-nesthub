from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_KNOWLEDGE, RUNTIME_DATASETS


class KnowledgeService:
    """Small local runtime knowledge service.

    This is intentionally generic. It does not know business domains. It stores
    and retrieves previous successful runtime results as evidence packets. The
    executor can use this before web/API/codegen when the local knowledge covers
    the current runtime parameters.
    """

    def search(
        self,
        query: str,
        *,
        required_terms: dict[str, list[str]] | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        query_terms = self._terms(query)
        required_terms = required_terms or {}
        candidates: list[dict[str, Any]] = []
        for path in self._knowledge_files():
            for row in self._read_jsonl(path):
                text = self._flatten_text(row)
                if not text.strip():
                    continue
                score = self._score(text, query_terms, required_terms)
                if score <= 0:
                    continue
                candidates.append({
                    "source": str(path),
                    "score": score,
                    "coverage": self._coverage(text, required_terms),
                    "record": row,
                    "text_excerpt": text[:3000],
                })
        candidates.sort(key=lambda x: x.get("score", 0), reverse=True)
        return candidates[: max(1, int(limit))]

    def best_covered(
        self,
        query: str,
        *,
        required_terms: dict[str, list[str]] | None = None,
        min_score: float = 1.0,
    ) -> dict[str, Any] | None:
        for item in self.search(query, required_terms=required_terms, limit=10):
            coverage = item.get("coverage") if isinstance(item.get("coverage"), dict) else {}
            if coverage.get("passed") and float(item.get("score") or 0) >= min_score:
                return item
        return None

    def save_success_case(self, run_id: str, data: dict) -> None:
        RUNTIME_KNOWLEDGE.mkdir(parents=True, exist_ok=True)
        with (RUNTIME_KNOWLEDGE / "success_cases.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "run_id": run_id,
                "created_at": datetime.utcnow().isoformat(),
                "data": data,
            }, ensure_ascii=False) + "\n")

    def _knowledge_files(self) -> list[Path]:
        files: list[Path] = []
        for base in [RUNTIME_KNOWLEDGE, RUNTIME_DATASETS]:
            if base.exists():
                files.extend(sorted(base.glob("*.jsonl")))
        return files

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        try:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    rows.append(obj)
        except Exception:
            return []
        return rows

    def _score(self, text: str, query_terms: set[str], required_terms: dict[str, list[str]]) -> float:
        low = text.lower()
        score = 0.0
        for term in query_terms:
            if term and term in low:
                score += 0.2
        coverage = self._coverage(text, required_terms)
        score += float(coverage.get("coverage_ratio") or 0) * 5.0
        if coverage.get("passed"):
            score += 5.0
        return score

    def _coverage(self, text: str, required_terms: dict[str, list[str]]) -> dict[str, Any]:
        if not required_terms:
            return {"passed": False, "coverage_ratio": 0.0, "matched": {}, "missing": []}
        low = text.lower()
        matched: dict[str, list[str]] = {}
        missing: list[str] = []
        for key, aliases in required_terms.items():
            found = []
            for alias in aliases:
                if str(alias).strip() and str(alias).lower() in low:
                    found.append(str(alias))
            if found:
                matched[key] = found[:5]
            else:
                missing.append(key)
        total = max(1, len(required_terms))
        ratio = (total - len(missing)) / total
        return {"passed": not missing, "coverage_ratio": ratio, "matched": matched, "missing": missing}

    def _terms(self, query: str) -> set[str]:
        return {t.lower() for t in re.findall(r"[A-Za-z0-9_\-]{3,}", str(query or ""))}

    def _flatten_text(self, value: Any, *, max_chars: int = 20000) -> str:
        parts: list[str] = []
        def walk(v: Any) -> None:
            if len("\n".join(parts)) > max_chars:
                return
            if isinstance(v, str):
                parts.append(v)
            elif isinstance(v, (int, float, bool)) or v is None:
                parts.append(str(v))
            elif isinstance(v, dict):
                for k, vv in v.items():
                    if str(k).lower() in {"provenance", "trace", "raw_html"}:
                        continue
                    parts.append(str(k))
                    walk(vv)
            elif isinstance(v, list):
                for item in v[:50]:
                    walk(item)
        walk(value)
        return "\n".join(parts)[:max_chars]
