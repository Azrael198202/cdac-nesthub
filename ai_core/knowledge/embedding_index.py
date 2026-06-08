from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class EmbeddingRecord:
    id: str
    vector: list[float]
    text: str
    metadata: dict[str, Any]
    created_at: str


class LocalTextEmbedder:
    """Deterministic local text embedder for offline runtime retrieval.

    This is a generic fallback embedder.  It does not encode domain knowledge or
    business-specific rules.  External embedding providers can replace it later
    while preserving the same record contract.
    """

    def __init__(self, *, dimension: int = 256) -> None:
        self.dimension = max(32, int(dimension or 256))
        self.provider_id = f"local_hash_ngram_{self.dimension}"

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        features = self._features(text)
        if not features:
            return vector
        for feature, weight in features:
            digest = hashlib.sha256(feature.encode("utf-8", errors="ignore")).digest()
            position = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[position] += sign * weight
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def _features(self, text: str) -> list[tuple[str, float]]:
        value = str(text or "").strip().lower()
        if not value:
            return []
        features: list[tuple[str, float]] = []
        tokens = re.findall(r"[\w\-]{2,}", value, flags=re.UNICODE)
        for token in tokens:
            features.append((f"tok:{token}", 1.0))
        for left, right in zip(tokens, tokens[1:]):
            features.append((f"bi:{left} {right}", 1.25))
        compact = re.sub(r"\s+", "", value)
        # Character n-grams improve recall for languages that do not use spaces.
        for size, weight in ((2, 0.45), (3, 0.7), (4, 0.55)):
            if len(compact) >= size:
                limit = min(len(compact) - size + 1, 800)
                for index in range(limit):
                    features.append((f"ch{size}:{compact[index:index + size]}", weight))
        return features[:4000]


class LocalVectorIndex:
    """JSONL-backed vector index with deterministic scoring.

    The index stores embeddings under runtime data paths.  It is intentionally
    dependency-light so Phase 1-C works in local/offline deployments.  A future
    vector database adapter can be added behind this contract without changing
    callers.
    """

    def __init__(self, *, root: Path, index_name: str = "default", embedder: LocalTextEmbedder | None = None) -> None:
        self.root = Path(root)
        self.index_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(index_name or "default")).strip("._-") or "default"
        self.embedder = embedder or LocalTextEmbedder()
        self.index_dir = self.root / "indexes" / self.index_name
        self.embedding_dir = self.root / "embeddings" / self.index_name
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.embedding_dir.mkdir(parents=True, exist_ok=True)
        self.records_path = self.index_dir / "vectors.jsonl"
        self.manifest_path = self.index_dir / "manifest.json"

    def upsert_texts(self, records: Iterable[dict[str, Any]]) -> dict[str, Any]:
        rows = list(records)
        now = datetime.utcnow().isoformat()
        written = 0
        with self.records_path.open("a", encoding="utf-8") as vector_file:
            for row in rows:
                text = str(row.get("text") or "").strip()
                record_id = str(row.get("id") or row.get("chunk_id") or "").strip()
                if not text or not record_id:
                    continue
                metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
                vector = self.embedder.embed(text)
                payload = {
                    "id": record_id,
                    "text": text,
                    "metadata": metadata,
                    "vector": vector,
                    "embedding_provider": self.embedder.provider_id,
                    "created_at": now,
                }
                vector_file.write(json.dumps(payload, ensure_ascii=False) + "\n")
                self._write_embedding_cache(record_id, payload)
                written += 1
        self._write_manifest(written_delta=written)
        return {"ok": True, "indexed_count": written, "embedding_provider": self.embedder.provider_id}

    def search(self, query: str, *, limit: int = 5, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        q = str(query or "").strip()
        if not q:
            return []
        query_vector = self.embedder.embed(q)
        filters = filters or {}
        scored: list[dict[str, Any]] = []
        for row in self._read_vector_rows():
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            if not self._matches_filters(metadata, filters):
                continue
            score = self._cosine(query_vector, row.get("vector") or [])
            lexical = self._lexical_overlap(q, str(row.get("text") or ""))
            combined = (score * 0.78) + (lexical * 0.22)
            if combined <= 0:
                continue
            scored.append({
                "id": row.get("id"),
                "text": row.get("text") or "",
                "metadata": metadata,
                "score": combined,
                "vector_score": score,
                "lexical_score": lexical,
                "source": "local_vector_index",
            })
        scored.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
        return scored[: max(1, int(limit or 5))]

    def stats(self) -> dict[str, Any]:
        rows = self._read_vector_rows()
        return {
            "index_name": self.index_name,
            "embedding_provider": self.embedder.provider_id,
            "vector_count": len(rows),
            "records_path": str(self.records_path),
            "embedding_dir": str(self.embedding_dir),
        }

    def _write_embedding_cache(self, record_id: str, payload: dict[str, Any]) -> None:
        safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", record_id).strip("._-") or hashlib.sha256(record_id.encode()).hexdigest()[:16]
        cache_path = self.embedding_dir / f"{safe_id}.json"
        cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_manifest(self, *, written_delta: int) -> None:
        existing: dict[str, Any] = {}
        if self.manifest_path.exists():
            try:
                existing = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            except Exception:
                existing = {}
        total = int(existing.get("indexed_count") or 0) + int(written_delta or 0)
        manifest = {
            "index_name": self.index_name,
            "embedding_provider": self.embedder.provider_id,
            "indexed_count": total,
            "updated_at": datetime.utcnow().isoformat(),
        }
        self.manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    def _read_vector_rows(self) -> list[dict[str, Any]]:
        if not self.records_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.records_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
        return rows

    def _matches_filters(self, metadata: dict[str, Any], filters: dict[str, Any]) -> bool:
        for key, expected in filters.items():
            if expected is None or expected == "":
                continue
            if metadata.get(key) != expected:
                return False
        return True

    def _lexical_overlap(self, query: str, text: str) -> float:
        q_terms = set(re.findall(r"[\w\-]{2,}", str(query or "").lower(), flags=re.UNICODE))
        if not q_terms:
            return 0.0
        low = str(text or "").lower()
        matched = sum(1 for term in q_terms if term in low)
        return matched / max(1, len(q_terms))

    def _cosine(self, left: list[float], right: list[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        return sum(a * b for a, b in zip(left, right))
