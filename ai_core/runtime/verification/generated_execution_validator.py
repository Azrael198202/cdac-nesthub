from __future__ import annotations

from typing import Any


class GeneratedExecutionValidator:
    """Rejects generated execution results without evidence linkage."""

    def validate(self, result: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(result, dict):
            return {"passed": False, "reason": "not_a_mapping"}
        provenance = result.get("provenance") if isinstance(result.get("provenance"), dict) else {}
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        source_url = provenance.get("source_url") or data.get("source_url")
        facts = data.get("facts") or data.get("structured_evidence")
        if source_url and facts:
            return {"passed": True, "reason": "evidence_linked"}
        return {"passed": False, "reason": "missing_evidence_linkage"}
