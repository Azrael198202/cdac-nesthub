from __future__ import annotations

from typing import Any
import hashlib


class MultiSourceEvidenceFusion:
    """Merges structured evidence from multiple sources without domain rules."""

    def fuse(self, materials: list[dict[str, Any]]) -> dict[str, Any]:
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for material in materials:
            for fact in self._facts(material):
                key = self._fingerprint(fact)
                if key in seen:
                    continue
                seen.add(key)
                normalized.append(fact)
        confidence = self._confidence(normalized)
        return {
            "type": "multi_source_fusion",
            "source_count": len({f.get("source_url") for f in normalized if f.get("source_url")}),
            "fact_count": len(normalized),
            "confidence": confidence,
            "facts": sorted(normalized, key=lambda f: float(f.get("confidence") or 0), reverse=True),
        }

    def _facts(self, material: dict[str, Any]) -> list[dict[str, Any]]:
        if not isinstance(material, dict):
            return []
        if isinstance(material.get("facts"), list):
            return [f for f in material["facts"] if isinstance(f, dict)]
        content = material.get("content") if isinstance(material.get("content"), dict) else {}
        if isinstance(content.get("facts"), list):
            return [f for f in content["facts"] if isinstance(f, dict)]
        return []

    def _fingerprint(self, fact: dict[str, Any]) -> str:
        payload = "|".join(str(fact.get(k) or "") for k in ("entity", "time", "attribute", "value", "unit"))
        return hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()

    def _confidence(self, facts: list[dict[str, Any]]) -> float:
        if not facts:
            return 0.0
        source_count = len({f.get("source_url") for f in facts if f.get("source_url")})
        avg = sum(float(f.get("confidence") or 0) for f in facts) / len(facts)
        bonus = min(source_count, 3) * 0.08
        return round(min(1.0, avg + bonus), 3)
