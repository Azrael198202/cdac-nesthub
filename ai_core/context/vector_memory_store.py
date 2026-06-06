from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ai_core.config.paths import RUNTIME_KNOWLEDGE


class VectorMemoryStore:
    """Small vector-like memory layer with optional Chroma support.

    The local fallback uses deterministic hashed vectors, so tests and offline
    runs do not require an external vector service.  When Chroma is available,
    the same records are mirrored there for normal semantic retrieval.
    """

    def __init__(self, *, root: Path | None = None, collection_name: str = "runtime_memory") -> None:
        self.root = root or (RUNTIME_KNOWLEDGE / "vector_memory")
        self.root.mkdir(parents=True, exist_ok=True)
        self.records_path = self.root / "records.jsonl"
        self.collection_name = collection_name
        self.collection = self._open_chroma_collection()

    def add_text(
        self,
        *,
        text: str,
        metadata: dict[str, Any] | None = None,
        memory_type: str = "context_fragment",
        usage_scope: str = "retrieval_context",
    ) -> dict[str, Any]:
        content = str(text or "").strip()
        record = {
            "id": "mem_" + uuid4().hex[:16],
            "text": content,
            "metadata": metadata or {},
            "memory_type": memory_type,
            "usage_scope": usage_scope,
            "vector": self._embed(content),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if content:
            with self.records_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._chroma_add(record)
        return record

    def search(self, query: str, *, limit: int = 5, usage_scope: str | None = None) -> list[dict[str, Any]]:
        q = str(query or "").strip()
        if not q:
            return []
        chroma = self._chroma_search(q, limit=limit, usage_scope=usage_scope)
        if chroma:
            return chroma
        qv = self._embed(q)
        rows = self._read_records()
        scored: list[dict[str, Any]] = []
        for row in rows:
            if usage_scope and row.get("usage_scope") != usage_scope:
                continue
            score = self._cosine(qv, row.get("vector") or [])
            if score > 0:
                item = dict(row)
                item["score"] = score
                scored.append(item)
        scored.sort(key=lambda x: x.get("score", 0), reverse=True)
        return scored[: max(1, int(limit))]

    def _open_chroma_collection(self):
        try:
            import chromadb  # type: ignore
            client = chromadb.PersistentClient(path=str(self.root / "chroma"))
            return client.get_or_create_collection(name=self.collection_name)
        except Exception:
            return None

    def _chroma_add(self, record: dict[str, Any]) -> None:
        if self.collection is None:
            return
        try:
            metadata = dict(record.get("metadata") or {})
            metadata.update({"memory_type": record.get("memory_type"), "usage_scope": record.get("usage_scope")})
            self.collection.add(
                ids=[record["id"]],
                documents=[record["text"]],
                metadatas=[metadata],
                embeddings=[record["vector"]],
            )
        except Exception:
            return

    def _chroma_search(self, query: str, *, limit: int, usage_scope: str | None) -> list[dict[str, Any]]:
        if self.collection is None:
            return []
        try:
            where = {"usage_scope": usage_scope} if usage_scope else None
            res = self.collection.query(
                query_embeddings=[self._embed(query)],
                n_results=max(1, int(limit)),
                where=where,
            )
            ids = (res.get("ids") or [[]])[0]
            docs = (res.get("documents") or [[]])[0]
            metas = (res.get("metadatas") or [[]])[0]
            dists = (res.get("distances") or [[]])[0]
            out = []
            for idx, doc_id in enumerate(ids):
                out.append({
                    "id": doc_id,
                    "text": docs[idx] if idx < len(docs) else "",
                    "metadata": metas[idx] if idx < len(metas) else {},
                    "score": 1.0 / (1.0 + float(dists[idx] if idx < len(dists) else 0.0)),
                    "source": "chroma",
                })
            return out
        except Exception:
            return []

    def _read_records(self) -> list[dict[str, Any]]:
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

    def _embed(self, text: str, *, dim: int = 128) -> list[float]:
        vec = [0.0] * dim
        tokens = [t for t in str(text or "").replace("\n", " ").split(" ") if t.strip()]
        if not tokens:
            return vec
        for tok in tokens:
            h = hashlib.sha256(tok.lower().encode("utf-8", errors="ignore")).digest()
            pos = int.from_bytes(h[:4], "big") % dim
            sign = 1.0 if h[4] % 2 == 0 else -1.0
            vec[pos] += sign
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    def _cosine(self, a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        return sum(x * y for x, y in zip(a, b))
