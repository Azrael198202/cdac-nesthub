from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_KNOWLEDGE, RUNTIME_DATASETS


class KnowledgeService:
    """Small local runtime knowledge service.

    v70.11 separates *knowledge that can answer the user* from *knowledge that
    only helps the runtime*.  Prompt optimization memories, workflow templates,
    and success-pattern records are useful hints, but they must never be used as
    final answer evidence.  This class stays domain-neutral by classifying
    records by generic memory metadata and internal-structure signals instead of
    by business-specific words.
    """

    FINAL_ANSWER_MEMORY_TYPES = {
        "factual_observation",
        "verified_web_evidence",
        "tool_execution_result",
        "user_provided_document_fact",
        "answer_result",
        "verified_result",
    }

    HINT_ONLY_MEMORY_TYPES = {
        "success_pattern",
        "prompt_optimization",
        "workflow_template",
        "schema_repair",
        "routing_hint",
        "planning_pattern",
    }

    INTERNAL_NODE_TYPES = {
        "input_parsing",
        "intent_recognition",
        "context_awareness",
        "workflow_planning",
        "execution",
        "feedback_learning",
        "output",
    }

    def search(
        self,
        query: str,
        *,
        required_terms: dict[str, list[str]] | None = None,
        limit: int = 5,
        final_answer_only: bool = False,
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
                classification = self.classify_record(row, source_path=path, flattened_text=text)
                if final_answer_only and not classification.get("final_answer_eligible"):
                    continue
                candidates.append({
                    "source": str(path),
                    "score": score,
                    "coverage": self._coverage(text, required_terms),
                    "record": row,
                    "text_excerpt": text[:3000],
                    "classification": classification,
                    "memory_type": classification.get("memory_type"),
                    "usage_scope": classification.get("usage_scope"),
                })
        candidates.sort(key=lambda x: x.get("score", 0), reverse=True)
        return candidates[: max(1, int(limit))]

    def best_covered(
        self,
        query: str,
        *,
        required_terms: dict[str, list[str]] | None = None,
        min_score: float = 1.0,
        final_answer_only: bool = True,
    ) -> dict[str, Any] | None:
        for item in self.search(query, required_terms=required_terms, limit=10, final_answer_only=final_answer_only):
            coverage = item.get("coverage") if isinstance(item.get("coverage"), dict) else {}
            if coverage.get("passed") and float(item.get("score") or 0) >= min_score:
                return item
        return None


    def best_hint(
        self,
        query: str,
        *,
        required_terms: dict[str, list[str]] | None = None,
    ) -> dict[str, Any] | None:
        """Return a matching hint-only record for prompt/workflow optimization.

        The caller may use this as context, but not as final answer material.
        """
        for item in self.search(query, required_terms=required_terms, limit=10, final_answer_only=False):
            classification = item.get("classification") if isinstance(item.get("classification"), dict) else {}
            if classification.get("usage_scope") == "hint_only":
                return item
        return None

    def classify_record(self, row: dict[str, Any], *, source_path: Path | None = None, flattened_text: str = "") -> dict[str, Any]:
        memory_type = self._memory_type(row)
        source_name = str(source_path or "").lower()
        node_id = str(row.get("node_id") or row.get("_node_id") or "").lower()
        if isinstance(row.get("data"), dict):
            node_id = node_id or str((row.get("data") or {}).get("node_id") or "").lower()

        reasons: list[str] = []
        if memory_type in self.HINT_ONLY_MEMORY_TYPES:
            reasons.append(f"memory_type={memory_type}_is_hint_only")
        if "prompt_optimization" in source_name:
            reasons.append("source_is_prompt_optimization_memory")
        if node_id in self.INTERNAL_NODE_TYPES and memory_type not in self.FINAL_ANSWER_MEMORY_TYPES:
            reasons.append(f"node_id={node_id}_is_internal_runtime_stage")
        if self._looks_like_runtime_structure(row, flattened_text):
            reasons.append("record_looks_like_runtime_structure_not_user_answer")

        final_answer_eligible = False
        if memory_type in self.FINAL_ANSWER_MEMORY_TYPES and not reasons:
            final_answer_eligible = True

        # Tool execution results may be stored without a memory_type. Allow only
        # when they explicitly contain user-facing answer/result fields or verified
        # evidence quality. Do not allow workflow/planning structures.
        if not memory_type and not reasons:
            if self._has_user_answer_payload(row):
                final_answer_eligible = True

        return {
            "memory_type": memory_type or "unknown",
            "usage_scope": "final_answer_evidence" if final_answer_eligible else "hint_only",
            "final_answer_eligible": final_answer_eligible,
            "reasons": reasons,
        }

    def _memory_type(self, row: dict[str, Any]) -> str:
        candidates = [row.get("memory_type")]
        for key in ("data", "metadata", "record"):
            nested = row.get(key) if isinstance(row.get(key), dict) else {}
            candidates.append(nested.get("memory_type"))
        for item in candidates:
            if isinstance(item, str) and item.strip():
                return item.strip().lower()
        return ""

    def _looks_like_runtime_structure(self, row: dict[str, Any], text: str) -> bool:
        runtime_keys = {
            "planned_steps", "approved_structure", "_executor_type", "_node_id",
            "_adapter_id", "required_capabilities", "blocking_missing_information",
            "human_interaction", "execution_ready", "next_action", "source_run_id",
        }
        found = 0
        def walk(v: Any) -> None:
            nonlocal found
            if found >= 3:
                return
            if isinstance(v, dict):
                for k, vv in v.items():
                    if str(k) in runtime_keys:
                        found += 1
                    walk(vv)
            elif isinstance(v, list):
                for item in v[:20]:
                    walk(item)
        walk(row)
        low = (text or "").lower()
        markers = ["planned_steps", "workflow_planning", "approved_structure", "_executor_type", "recommendation"]
        found += sum(1 for m in markers if m in low)
        return found >= 3

    def _has_user_answer_payload(self, row: dict[str, Any]) -> bool:
        answer_keys = {"final_answer", "answer", "summary", "message", "text", "answer_material"}
        quality_passed = False
        found_answer = False
        def walk(v: Any) -> None:
            nonlocal found_answer, quality_passed
            if isinstance(v, dict):
                q = v.get("answer_material_quality")
                if isinstance(q, dict) and q.get("passed") is True:
                    quality_passed = True
                for k, vv in v.items():
                    if str(k) in answer_keys and isinstance(vv, str) and vv.strip():
                        found_answer = True
                    walk(vv)
            elif isinstance(v, list):
                for item in v[:20]:
                    walk(item)
        walk(row)
        return found_answer and quality_passed


    def save_answer_result(self, *, run_id: str, query: str, final_answer: str, facts: list[dict[str, Any]] | None = None, trust_summary: dict[str, Any] | None = None) -> None:
        """Persist a verified user-facing answer for later local retrieval.

        Runtime outputs are stored as data, not shipped with source packages.
        This method intentionally writes only final-answer evidence records and
        compact verified facts, not raw pages or intermediate node JSON.
        """
        RUNTIME_KNOWLEDGE.mkdir(parents=True, exist_ok=True)
        record = {
            "memory_type": "answer_result",
            "usage_scope": "final_answer_evidence",
            "run_id": run_id,
            "query": query,
            "final_answer": final_answer,
            "facts": facts or [],
            "trust_summary": trust_summary or {},
            "created_at": datetime.utcnow().isoformat(),
        }
        with (RUNTIME_KNOWLEDGE / "answer_results.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def answer_from_knowledge(self, query: str, *, required_terms: dict[str, list[str]] | None = None) -> dict[str, Any] | None:
        item = self.best_covered(query, required_terms=required_terms, min_score=1.0, final_answer_only=True)
        if not item:
            return None
        row = item.get("record") if isinstance(item.get("record"), dict) else {}
        answer = row.get("final_answer") or row.get("answer") or row.get("message")
        if not isinstance(answer, str) or not answer.strip():
            return None
        return {
            "answer": answer.strip(),
            "source": item.get("source"),
            "score": item.get("score"),
            "memory_type": item.get("memory_type"),
        }

    def status(self) -> dict[str, Any]:
        files = self._knowledge_files()
        rows = 0
        eligible = 0
        for path in files:
            for row in self._read_jsonl(path):
                rows += 1
                if self.classify_record(row, source_path=path, flattened_text=self._flatten_text(row)).get("final_answer_eligible"):
                    eligible += 1
        return {
            "enabled": True,
            "paths": [str(RUNTIME_KNOWLEDGE), str(RUNTIME_DATASETS)],
            "file_count": len(files),
            "record_count": rows,
            "final_answer_eligible_count": eligible,
        }

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
