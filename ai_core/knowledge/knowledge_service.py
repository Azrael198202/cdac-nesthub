from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from ai_core.config.paths import RUNTIME_DATASETS, RUNTIME_KNOWLEDGE
from ai_core.knowledge.document_processor import DocumentChunker, DocumentTextExtractor, SUPPORTED_EXTENSIONS
from ai_core.knowledge.embedding_index import LocalVectorIndex
from ai_core.llm.provider_handlers.base import ProviderUnavailableError
from ai_core.llm.provider_router import ProviderRouter
from ai_core.utils.safe_json import make_json_safe


class KnowledgeService:
    """Local runtime knowledge service with chunk and embedding lifecycles."""

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

    def __init__(self) -> None:
        self.provider_router = ProviderRouter()

    def ingest_file(
        self,
        *,
        file_path: str | Path,
        original_name: str | None = None,
        content_type: str | None = None,
        knowledge_base_id: str | None = None,
    ) -> dict[str, Any]:
        source_path = Path(file_path)
        kb_id = self._safe_id(knowledge_base_id or "default")
        document_id = "doc_" + uuid4().hex[:16]
        root = self._document_root(kb_id)
        now = datetime.utcnow().isoformat()

        processing_state = self._processing_state(
            knowledge_base_id=kb_id,
            document_id=document_id,
            status="extracting",
            updated_at=now,
        )
        self._write_json(root / "processing" / f"{document_id}.json", processing_state)

        extractor = DocumentTextExtractor()
        extracted = extractor.extract(source_path, original_name=original_name, content_type=content_type)
        raw_dir = root / "files"
        document_dir = root / "documents"
        chunk_dir = root / "chunks"
        raw_dir.mkdir(parents=True, exist_ok=True)
        document_dir.mkdir(parents=True, exist_ok=True)
        chunk_dir.mkdir(parents=True, exist_ok=True)

        stored_path = raw_dir / f"{document_id}{source_path.suffix.lower()}"
        if source_path.exists() and source_path.resolve() != stored_path.resolve():
            stored_path.write_bytes(source_path.read_bytes())

        document_payload = {
            "document_id": document_id,
            "knowledge_base_id": kb_id,
            "filename": original_name or source_path.name,
            "stored_path": str(stored_path if stored_path.exists() else source_path),
            "source_path": str(source_path),
            "content_type": content_type or extracted.metadata.get("content_type") or "",
            "extension": extracted.metadata.get("extension") or source_path.suffix.lower(),
            "size_bytes": extracted.metadata.get("size_bytes") or (source_path.stat().st_size if source_path.exists() else 0),
            "text": extracted.text,
            "warnings": extracted.warnings,
            "created_at": now,
            "updated_at": now,
        }
        self._write_json(document_dir / f"{document_id}.json", document_payload)

        processing_state.update({"status": "chunking", "updated_at": datetime.utcnow().isoformat()})
        self._write_json(root / "processing" / f"{document_id}.json", processing_state)
        chunker = DocumentChunker()
        chunks = chunker.chunk(extracted.text, document_id=document_id)
        chunk_records: list[dict[str, Any]] = []
        for chunk in chunks:
            record = {
                "memory_type": self.DOCUMENT_MEMORY_TYPE,
                "usage_scope": self.DOCUMENT_USAGE_SCOPE,
                "knowledge_base_id": kb_id,
                "document_id": document_id,
                "chunk_id": chunk["chunk_id"],
                "chunk_index": chunk["chunk_index"],
                "text": chunk["text"],
                "metadata": {
                    "filename": document_payload["filename"],
                    "document_id": document_id,
                    "knowledge_base_id": kb_id,
                    "chunk_id": chunk["chunk_id"],
                    "chunk_index": chunk["chunk_index"],
                    "char_start": chunk.get("char_start"),
                    "char_end": chunk.get("char_end"),
                    "token_estimate": chunk.get("token_estimate"),
                    "previous_chunk_id": chunk.get("previous_chunk_id"),
                    "next_chunk_id": chunk.get("next_chunk_id"),
                },
                "created_at": now,
            }
            chunk_records.append(record)
        self._write_jsonl(chunk_dir / f"{document_id}.jsonl", chunk_records, append=False)
        self._append_jsonl(root / "chunks.jsonl", chunk_records)

        processing_state.update({"status": "embedding", "updated_at": datetime.utcnow().isoformat()})
        self._write_json(root / "processing" / f"{document_id}.json", processing_state)
        index = self._vector_index(kb_id)
        index_result = index.upsert_texts([
            {
                "id": record["chunk_id"],
                "text": record["text"],
                "metadata": record["metadata"],
            }
            for record in chunk_records
        ])

        status = "indexed" if chunk_records else "empty"
        meta = {
            "document_id": document_id,
            "knowledge_base_id": kb_id,
            "filename": document_payload["filename"],
            "stored_path": document_payload["stored_path"],
            "source_path": document_payload["source_path"],
            "content_type": document_payload["content_type"],
            "extension": document_payload["extension"],
            "size_bytes": document_payload["size_bytes"],
            "status": status,
            "chunk_count": len(chunk_records),
            "embedding_count": int(index_result.get("indexed_count") or 0),
            "embedding_provider": index_result.get("embedding_provider"),
            "warnings": extracted.warnings,
            "created_at": now,
            "updated_at": datetime.utcnow().isoformat(),
        }
        self._append_jsonl(root / "documents.jsonl", meta)
        self._update_registry(kb_id, meta)
        processing_state.update({
            "status": status,
            "chunk_count": len(chunk_records),
            "embedding_count": int(index_result.get("indexed_count") or 0),
            "updated_at": datetime.utcnow().isoformat(),
        })
        self._write_json(root / "processing" / f"{document_id}.json", processing_state)
        return {"ok": True, "status": status, "document": meta, "chunk_count": len(chunk_records), "embedding": index_result}

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
            vector_hits = self._vector_index(kb_id).search(q, limit=limit)
            for hit in vector_hits:
                meta = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
                results.append({
                    "knowledge_base_id": kb_id,
                    "document_id": meta.get("document_id"),
                    "chunk_id": meta.get("chunk_id") or hit.get("id"),
                    "chunk_index": meta.get("chunk_index"),
                    "filename": meta.get("filename"),
                    "text": hit.get("text") or "",
                    "score": float(hit.get("score") or 0.0),
                    "vector_score": hit.get("vector_score"),
                    "lexical_score": hit.get("lexical_score"),
                    "source": hit.get("source") or "local_vector_index",
                })
            if not vector_hits:
                results.extend(self._keyword_search_documents(q, kb_id=kb_id, limit=limit))
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
                "chunk_id": hit.get("chunk_id"),
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


    def has_relevant_evidence(
        self,
        query: str,
        *,
        knowledge_base_id: str | None = None,
        limit: int = 5,
        min_score: float = 0.18,
        min_lexical_score: float = 0.12,
    ) -> dict[str, Any]:
        """Probe whether local evidence is strong enough to answer a user message.

        This is a generic evidence gate.  It does not inspect domain words or
        task names.  The decision is based only on retrieval scores and the
        availability of non-empty local evidence material.
        """
        hits = self.search_documents(query, knowledge_base_id=knowledge_base_id, limit=limit)
        usable: list[dict[str, Any]] = []
        for hit in hits:
            text = str(hit.get("text") or "").strip()
            if not text:
                continue
            score = float(hit.get("score") or 0.0)
            lexical = float(hit.get("lexical_score") or 0.0)
            vector = float(hit.get("vector_score") or 0.0)
            if score >= float(min_score) and (lexical >= float(min_lexical_score) or vector >= float(min_score)):
                usable.append(hit)
        return {
            "ok": True,
            "relevant": bool(usable),
            "status": "evidence_found" if usable else "no_relevant_evidence",
            "results": usable[: max(1, int(limit or 5))],
            "top_score": float(usable[0].get("score") or 0.0) if usable else 0.0,
        }

    async def rag_answer(
        self,
        query: str,
        *,
        knowledge_base_id: str | None = None,
        limit: int = 5,
        synthesize: bool = True,
        response_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Retrieve local evidence and synthesize a grounded answer.

        The method is intentionally generic: it treats retrieved chunks as
        evidence material and asks the configured synthesis model to produce an
        answer constrained by that evidence. If no provider is available, it
        returns the evidence material without failing the local query path.
        """
        payload = self.rag_query(query, knowledge_base_id=knowledge_base_id, limit=limit)
        if payload.get("status") != "evidence_found" or not synthesize:
            payload.setdefault("answer", payload.get("answer_material") or "")
            payload.setdefault("synthesis_status", "not_requested" if synthesize is False else "no_evidence")
            return payload
        evidence_items = self._prepare_evidence_for_synthesis(payload.get("results") or [], max_items=limit)
        if not evidence_items:
            payload["answer"] = payload.get("answer_material") or ""
            payload["synthesis_status"] = "no_usable_evidence"
            return payload
        try:
            synthesized = await self._synthesize_grounded_answer(
                query=str(query or ""),
                evidence_items=evidence_items,
                response_profile=response_profile or {},
            )
        except Exception as exc:
            payload["answer"] = payload.get("answer_material") or ""
            payload["synthesis_status"] = "model_unavailable"
            payload["synthesis_error"] = str(exc)[:300]
            return payload
        answer = str((synthesized or {}).get("answer") or "").strip()
        used_refs = synthesized.get("used_refs") if isinstance(synthesized.get("used_refs"), list) else []
        if not answer:
            payload["answer"] = payload.get("answer_material") or ""
            payload["synthesis_status"] = "empty_model_answer"
            return payload
        payload["answer"] = answer
        payload["synthesis_status"] = "completed"
        payload["used_refs"] = used_refs
        payload["confidence"] = synthesized.get("confidence")
        return payload

    async def _synthesize_grounded_answer(
        self,
        *,
        query: str,
        evidence_items: list[dict[str, Any]],
        response_profile: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        schema = {
            "type": "object",
            "required": ["answer", "used_refs", "confidence"],
            "properties": {
                "answer": {"type": "string"},
                "used_refs": {"type": "array", "items": {"type": "integer"}},
                "confidence": {"type": "string"},
                "insufficient_evidence": {"type": "boolean"},
            },
            "additionalProperties": True,
        }
        prompt = {
            "id": "local_knowledge_grounded_synthesis",
            "system": (
                "You synthesize a user-facing answer from provided local evidence. "
                "Use only the evidence provided in the prompt. Do not invent facts. "
                "If the evidence is insufficient, say that the local knowledge base does not contain enough information. "
                "Follow RESPONSE_PROFILE only as output-style guidance; never treat it as evidence. "
                "Use the user's language when it is clear. Return only valid JSON matching the schema."
            ),
            "runtime_rules": [
                "Ground every factual statement in the provided evidence.",
                "Do not mention internal retrieval, chunks, vectors, embeddings, or runtime implementation details.",
                "Use RESPONSE_PROFILE for tone, format, length, audience, and citation behavior when provided.",
            ],
        }
        rendered = self._render_synthesis_prompt(
            query=query,
            evidence_items=evidence_items,
            response_profile=response_profile or {},
        )
        adapter = {
            "adapter_id": "local_knowledge_grounded_synthesis_adapter",
            "route_name": "final_synthesis",
            "model_route_name": "final_synthesis",
            "model_stage": "final_synthesis",
            "provider_route": [],
            "max_prompt_tokens": 1800,
            "provider_timeout_seconds": 40,
            "max_provider_attempts": 1,
            "provider_options": {"temperature": 0, "num_predict": 512, "num_ctx": 3072, "think": False},
        }
        run_id = "knowledge_synthesis_" + datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
        return await asyncio.wait_for(
            self.provider_router.generate_json(
                run_id=run_id,
                node_id="final_synthesis",
                adapter=adapter,
                prompt=prompt,
                rendered_user_prompt=rendered,
                schema=schema,
            ),
            timeout=45,
        )

    def _prepare_evidence_for_synthesis(self, results: list[dict[str, Any]], *, max_items: int = 5) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for idx, hit in enumerate(results[: max(1, int(max_items or 5))], start=1):
            text = self._compact_excerpt(str(hit.get("text") or ""), max_chars=1200)
            if not text:
                continue
            items.append({
                "ref": idx,
                "text": text,
                "filename": hit.get("filename"),
                "document_id": hit.get("document_id"),
                "chunk_id": hit.get("chunk_id"),
                "score": hit.get("score"),
            })
        return items

    def _render_synthesis_prompt(
        self,
        *,
        query: str,
        evidence_items: list[dict[str, Any]],
        response_profile: dict[str, Any] | None = None,
    ) -> str:
        lines = ["USER_QUESTION:", str(query or "").strip(), ""]
        clean_profile = self._clean_response_profile(response_profile or {})
        if clean_profile:
            lines.extend([
                "RESPONSE_PROFILE_JSON:",
                json.dumps(make_json_safe(clean_profile), ensure_ascii=False, separators=(",", ":"))[:1200],
                "",
            ])
        lines.append("LOCAL_EVIDENCE:")
        for item in evidence_items:
            lines.append(f"[{int(item.get('ref') or 0)}]")
            lines.append(str(item.get("text") or ""))
            lines.append("")
        lines.append("ANSWER_REQUIREMENT:")
        lines.append("Produce the final answer directly, based only on LOCAL_EVIDENCE. Include no hidden reasoning.")
        return "\n".join(lines)


    def _clean_response_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        """Return generic, user-facing synthesis instructions.

        This method is intentionally structural: it accepts only neutral output
        profile keys and never encodes domain, task, company, product, or sample
        phrases in source code.
        """
        if not isinstance(profile, dict):
            return {}
        allowed = {
            "output_type",
            "tone",
            "format",
            "language",
            "length",
            "audience",
            "citation_style",
            "detail_level",
            "source_policy",
        }
        cleaned: dict[str, Any] = {}
        for key, value in profile.items():
            normalized_key = str(key or "").strip()
            if normalized_key not in allowed:
                continue
            if value in (None, "", [], {}):
                continue
            if isinstance(value, (str, int, float, bool, list, dict)):
                cleaned[normalized_key] = value
        return cleaned

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

    def best_hint(self, query: str, *, required_terms: dict[str, list[str]] | None = None) -> dict[str, Any] | None:
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
        if not memory_type and not reasons and self._has_user_answer_payload(row):
            final_answer_eligible = True
        return {
            "memory_type": memory_type or "unknown",
            "usage_scope": "final_answer_evidence" if final_answer_eligible else "hint_only",
            "final_answer_eligible": final_answer_eligible,
            "reasons": reasons,
        }

    def save_answer_result(self, *, run_id: str, query: str, final_answer: str, facts: list[dict[str, Any]] | None = None, trust_summary: dict[str, Any] | None = None) -> None:
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
        return {"answer": answer.strip(), "source": item.get("source"), "score": item.get("score"), "memory_type": item.get("memory_type")}

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
        chunk_count = 0
        embedding_count = 0
        vector_stats: dict[str, Any] = {}
        for kb_id in document_state.get("knowledge_bases") or ["default"]:
            root = self._document_root(kb_id)
            for path in (root / "chunks").glob("*.jsonl") if (root / "chunks").exists() else []:
                chunk_count += len(self._read_jsonl(path))
            stats = self._vector_index(kb_id).stats()
            embedding_count += int(stats.get("vector_count") or 0)
            vector_stats[kb_id] = stats
        return {
            "enabled": True,
            "paths": [str(RUNTIME_KNOWLEDGE), str(RUNTIME_DATASETS)],
            "file_count": len(files),
            "record_count": rows,
            "final_answer_eligible_count": eligible,
            "document_count": len(document_state.get("documents") or []),
            "chunk_count": chunk_count,
            "embedding_count": embedding_count,
            "knowledge_bases": document_state.get("knowledge_bases") or [],
            "supported_extensions": sorted(SUPPORTED_EXTENSIONS),
            "vector_indexes": vector_stats,
        }

    def save_success_case(self, run_id: str, data: dict) -> None:
        RUNTIME_KNOWLEDGE.mkdir(parents=True, exist_ok=True)
        with (RUNTIME_KNOWLEDGE / "success_cases.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"run_id": run_id, "created_at": datetime.utcnow().isoformat(), "data": data}, ensure_ascii=False) + "\n")

    def _keyword_search_documents(self, query: str, *, kb_id: str, limit: int) -> list[dict[str, Any]]:
        root = self._document_root(kb_id)
        query_terms = self._terms(query)
        results: list[dict[str, Any]] = []
        for row in self._read_jsonl(root / "chunks.jsonl"):
            text = str(row.get("text") or "")
            score = self._score(text, query_terms, {})
            if score <= 0:
                continue
            meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            results.append({
                "knowledge_base_id": kb_id,
                "document_id": row.get("document_id"),
                "chunk_id": row.get("chunk_id"),
                "chunk_index": row.get("chunk_index"),
                "filename": meta.get("filename"),
                "text": text,
                "score": score,
                "source": "keyword_chunk_index",
            })
        results.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
        return results[: max(1, int(limit))]

    def _knowledge_files(self) -> list[Path]:
        files: list[Path] = []
        for base in [RUNTIME_KNOWLEDGE, RUNTIME_DATASETS]:
            if base.exists():
                files.extend(sorted(base.glob("*.jsonl")))
        documents_root = RUNTIME_KNOWLEDGE / "document_bases"
        if documents_root.exists():
            files.extend(sorted(documents_root.glob("*/chunks.jsonl")))
            files.extend(sorted(documents_root.glob("*/chunks/*.jsonl")))
        return files

    def _document_root(self, knowledge_base_id: str) -> Path:
        return RUNTIME_KNOWLEDGE / "document_bases" / self._safe_id(knowledge_base_id or "default")

    def _vector_index(self, knowledge_base_id: str) -> LocalVectorIndex:
        return LocalVectorIndex(root=self._document_root(knowledge_base_id), index_name="chunks")

    def _knowledge_base_ids(self) -> list[str]:
        root = RUNTIME_KNOWLEDGE / "document_bases"
        if not root.exists():
            return ["default"]
        ids = [p.name for p in sorted(root.iterdir()) if p.is_dir()]
        return ids or ["default"]

    def _processing_state(self, **kwargs: Any) -> dict[str, Any]:
        payload = dict(kwargs)
        payload.setdefault("created_at", datetime.utcnow().isoformat())
        return payload

    def _update_registry(self, knowledge_base_id: str, document_meta: dict[str, Any]) -> None:
        root = self._document_root(knowledge_base_id)
        registry_path = root / "registry.json"
        registry = {"knowledge_base_id": knowledge_base_id, "documents": [], "updated_at": datetime.utcnow().isoformat()}
        if registry_path.exists():
            try:
                existing = json.loads(registry_path.read_text(encoding="utf-8"))
                if isinstance(existing, dict):
                    registry.update(existing)
            except Exception:
                pass
        docs = [item for item in registry.get("documents", []) if isinstance(item, dict) and item.get("document_id") != document_meta.get("document_id")]
        docs.append(document_meta)
        registry["documents"] = docs
        registry["updated_at"] = datetime.utcnow().isoformat()
        self._write_json(registry_path, registry)

    def _safe_id(self, value: str | None) -> str:
        raw = str(value or "default").strip() or "default"
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._-")
        return safe[:80] or "default"

    def _append_jsonl(self, path: Path, rows: dict[str, Any] | list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payloads = rows if isinstance(rows, list) else [rows]
        with path.open("a", encoding="utf-8") as f:
            for row in payloads:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _write_jsonl(self, path: Path, rows: list[dict[str, Any]], *, append: bool = False) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with path.open(mode, encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

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
            found = [str(alias) for alias in aliases if str(alias).strip() and str(alias).lower() in low]
            if found:
                matched[key] = found[:5]
            else:
                missing.append(key)
        total = max(1, len(required_terms))
        ratio = (total - len(missing)) / total
        return {"passed": not missing, "coverage_ratio": ratio, "matched": matched, "missing": missing}

    def _terms(self, query: str) -> set[str]:
        return {t.lower() for t in re.findall(r"[\w\-]{2,}", str(query or ""), flags=re.UNICODE)}

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
                    if str(k).lower() in {"provenance", "trace", "raw_html", "vector"}:
                        continue
                    parts.append(str(k))
                    walk(vv)
            elif isinstance(v, list):
                for item in v[:50]:
                    walk(item)
        walk(value)
        return "\n".join(parts)[:max_chars]

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
        found += sum(1 for marker in markers if marker in low)
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
