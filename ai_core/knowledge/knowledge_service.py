from __future__ import annotations

import json
import re
from datetime import datetime
from uuid import uuid4
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_KNOWLEDGE, RUNTIME_DATASETS
from ai_core.context.vector_memory_store import VectorMemoryStore
from ai_core.knowledge.document_processor import DocumentChunker, DocumentTextExtractor, SUPPORTED_EXTENSIONS


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


    DOCUMENT_MEMORY_TYPE = "user_provided_document_fact"
    DOCUMENT_USAGE_SCOPE = "final_answer_evidence"

    def ingest_file(
        self,
        *,
        file_path: str | Path,
        original_name: str | None = None,
        content_type: str | None = None,
        knowledge_base_id: str | None = None,
    ) -> dict[str, Any]:
        """Ingest one user-provided document into runtime knowledge.

        This method is domain-neutral: it extracts text, chunks it, stores chunk
        evidence, and mirrors chunks into the local vector memory store.  It does
        not infer business meaning from filenames or text.
        """
        source_path = Path(file_path)
        extractor = DocumentTextExtractor()
        extracted = extractor.extract(source_path, original_name=original_name, content_type=content_type)
        chunks = DocumentChunker().chunk(extracted.text)
        kb_id = self._safe_id(knowledge_base_id or "default")
        document_id = "doc_" + uuid4().hex[:16]
        root = self._document_root(kb_id)
        root.mkdir(parents=True, exist_ok=True)
        raw_dir = root / "files"
        raw_dir.mkdir(parents=True, exist_ok=True)
        stored_path = raw_dir / f"{document_id}{source_path.suffix.lower()}"
        if source_path.exists() and source_path.resolve() != stored_path.resolve():
            stored_path.write_bytes(source_path.read_bytes())
        now = datetime.utcnow().isoformat()
        meta = {
            "document_id": document_id,
            "knowledge_base_id": kb_id,
            "filename": original_name or source_path.name,
            "stored_path": str(stored_path if stored_path.exists() else source_path),
            "source_path": str(source_path),
            "content_type": content_type or extracted.metadata.get("content_type") or "",
            "extension": extracted.metadata.get("extension") or source_path.suffix.lower(),
            "size_bytes": extracted.metadata.get("size_bytes") or (source_path.stat().st_size if source_path.exists() else 0),
            "status": "indexed" if chunks else "empty",
            "chunk_count": len(chunks),
            "warnings": extracted.warnings,
            "created_at": now,
            "updated_at": now,
        }
        self._append_jsonl(root / "documents.jsonl", meta)
        chunk_records: list[dict[str, Any]] = []
        vector_store = VectorMemoryStore(root=root / "vector_memory", collection_name=f"kb_{kb_id}")
        for chunk in chunks:
            record = {
                "memory_type": self.DOCUMENT_MEMORY_TYPE,
                "usage_scope": self.DOCUMENT_USAGE_SCOPE,
                "knowledge_base_id": kb_id,
                "document_id": document_id,
                "chunk_id": f"{document_id}_chunk_{chunk['chunk_index']}",
                "chunk_index": chunk["chunk_index"],
                "text": chunk["text"],
                "metadata": {
                    "filename": meta["filename"],
                    "document_id": document_id,
                    "knowledge_base_id": kb_id,
                    "chunk_index": chunk["chunk_index"],
                },
                "created_at": now,
            }
            chunk_records.append(record)
            self._append_jsonl(root / "chunks.jsonl", record)
            vector_store.add_text(
                text=chunk["text"],
                metadata=record["metadata"],
                memory_type=self.DOCUMENT_MEMORY_TYPE,
                usage_scope=self.DOCUMENT_USAGE_SCOPE,
            )
        return {"ok": True, "status": meta["status"], "document": meta, "chunk_count": len(chunk_records)}

    def list_documents(self, *, knowledge_base_id: str | None = None) -> dict[str, Any]:
        kb_ids = [self._safe_id(knowledge_base_id)] if knowledge_base_id else self._knowledge_base_ids()
        documents: list[dict[str, Any]] = []
        for kb_id in kb_ids:
            root = self._document_root(kb_id)
            for row in self._read_jsonl(root / "documents.jsonl"):
                documents.append(row)
        documents.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return {"ok": True, "knowledge_bases": kb_ids, "documents": documents, "supported_extensions": sorted(SUPPORTED_EXTENSIONS)}

    def search_documents(self, query: str, *, knowledge_base_id: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
        q = str(query or "").strip()
        if not q:
            return []
        kb_ids = [self._safe_id(knowledge_base_id)] if knowledge_base_id else self._knowledge_base_ids()
        results: list[dict[str, Any]] = []
        for kb_id in kb_ids:
            root = self._document_root(kb_id)
            vector_hits = VectorMemoryStore(root=root / "vector_memory", collection_name=f"kb_{kb_id}").search(
                q, limit=limit, usage_scope=self.DOCUMENT_USAGE_SCOPE
            )
            if vector_hits:
                for hit in vector_hits:
                    meta = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
                    results.append({
                        "knowledge_base_id": kb_id,
                        "document_id": meta.get("document_id"),
                        "chunk_index": meta.get("chunk_index"),
                        "filename": meta.get("filename"),
                        "text": hit.get("text") or "",
                        "score": float(hit.get("score") or 0.0),
                        "source": hit.get("source") or "vector_memory",
                    })
            else:
                query_terms = self._terms(q)
                for row in self._read_jsonl(root / "chunks.jsonl"):
                    text = str(row.get("text") or "")
                    score = self._score(text, query_terms, {})
                    if score <= 0:
                        continue
                    meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
                    results.append({
                        "knowledge_base_id": kb_id,
                        "document_id": row.get("document_id"),
                        "chunk_index": row.get("chunk_index"),
                        "filename": meta.get("filename"),
                        "text": text,
                        "score": score,
                        "source": "chunk_index",
                    })
        results.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
        return results[: max(1, int(limit))]

    def rag_query(self, query: str, *, knowledge_base_id: str | None = None, limit: int = 5) -> dict[str, Any]:
        hits = self.search_documents(query, knowledge_base_id=knowledge_base_id, limit=limit)
        if not hits:
            return {
                "ok": True,
                "status": "no_evidence",
                "answer_material": "No matching local knowledge evidence was found.",
                "citations": [],
                "results": [],
            }
        citations = []
        lines = []
        for idx, hit in enumerate(hits, start=1):
            citations.append({
                "ref": idx,
                "knowledge_base_id": hit.get("knowledge_base_id"),
                "document_id": hit.get("document_id"),
                "filename": hit.get("filename"),
                "chunk_index": hit.get("chunk_index"),
                "score": hit.get("score"),
            })
            excerpt = self._compact_excerpt(str(hit.get("text") or ""))
            lines.append(f"[{idx}] {excerpt}")
        return {
            "ok": True,
            "status": "evidence_found",
            "answer_material": "\n\n".join(lines),
            "citations": citations,
            "results": hits,
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
        document_state = self.list_documents()
        return {
            "enabled": True,
            "paths": [str(RUNTIME_KNOWLEDGE), str(RUNTIME_DATASETS)],
            "file_count": len(files),
            "record_count": rows,
            "final_answer_eligible_count": eligible,
            "document_count": len(document_state.get("documents") or []),
            "knowledge_bases": document_state.get("knowledge_bases") or [],
            "supported_extensions": sorted(SUPPORTED_EXTENSIONS),
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
        documents_root = RUNTIME_KNOWLEDGE / "document_bases"
        if documents_root.exists():
            files.extend(sorted(documents_root.glob("*/chunks.jsonl")))
        return files

    def _document_root(self, knowledge_base_id: str) -> Path:
        return RUNTIME_KNOWLEDGE / "document_bases" / self._safe_id(knowledge_base_id or "default")

    def _knowledge_base_ids(self) -> list[str]:
        root = RUNTIME_KNOWLEDGE / "document_bases"
        if not root.exists():
            return ["default"]
        ids = [p.name for p in sorted(root.iterdir()) if p.is_dir()]
        return ids or ["default"]

    def _safe_id(self, value: str | None) -> str:
        raw = str(value or "default").strip() or "default"
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._-")
        return safe[:80] or "default"

    def _append_jsonl(self, path: Path, row: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _compact_excerpt(self, text: str, *, max_chars: int = 900) -> str:
        value = re.sub(r"\s+", " ", str(text or "")).strip()
        if len(value) <= max_chars:
            return value
        return value[:max_chars].rstrip() + " ..."

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
