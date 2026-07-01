from __future__ import annotations

import re
from typing import Any, Callable


class SourcePlanner:
    """Generic source policy planner for conversation/runtime execution.

    This planner does not contain business terms, domain terms, or language
    keyword routing lists.  It selects optional sources by evaluating upstream
    runtime decisions and the quality of retrievable evidence.

    Design rule:
    - ai_core decides source policy by generic signals and evidence quality.
    - concrete retrieval remains outside ai_core.
    - local knowledge is selected only after a probe returns relevant evidence.
    """

    VERSION = "source_planner.v2.generic_evidence_gated"

    def plan(
        self,
        text: str,
        *,
        intent: dict[str, Any] | None = None,
        knowledge_evaluation: dict[str, Any] | None = None,
        knowledge_status: dict[str, Any] | None = None,
        local_probe: Callable[[], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        value = str(text or "").strip()
        intent = intent if isinstance(intent, dict) else {}
        knowledge_evaluation = knowledge_evaluation if isinstance(knowledge_evaluation, dict) else {}
        knowledge_status = knowledge_status if isinstance(knowledge_status, dict) else {}
        decision: dict[str, Any] = {
            "version": self.VERSION,
            "selected_sources": [],
            "rejected_sources": [],
            "source_policy": "none",
            "local_knowledge": {"selected": False, "status": "not_requested", "reason": "not_evaluated"},
            "selection_basis": {
                "uses_domain_keywords": False,
                "uses_business_keywords": False,
                "uses_language_keyword_lists": False,
                "evidence_gated": True,
            },
        }
        if not value:
            return self._reject(decision, "local_knowledge", "empty_input")
        if bool(intent.get("capability_gap_detected")):
            return self._reject(decision, "local_knowledge", "capability_acquisition_has_dedicated_pipeline")
        if self._external_source_required(knowledge_evaluation, intent):
            decision["selected_sources"].append("external_source")
            decision["source_policy"] = "external_source"
            return self._reject(decision, "local_knowledge", "external_source_policy_selected")
        if not self._local_index_available(knowledge_status):
            return self._reject(decision, "local_knowledge", "no_local_document_chunks")
        if not callable(local_probe):
            return self._reject(decision, "local_knowledge", "local_probe_not_available")

        payload = local_probe()
        passed, reason, metrics = self._passes_local_evidence_gate(value, payload)
        if not passed:
            decision["local_knowledge"] = {
                "selected": False,
                "status": payload.get("status") if isinstance(payload, dict) else "not_available",
                "reason": reason,
                "metrics": metrics,
                "evidence": payload if isinstance(payload, dict) else {},
            }
            decision["rejected_sources"].append({"source": "local_knowledge", "reason": reason, "metrics": metrics})
            return decision

        decision["selected_sources"].append("local_knowledge")
        decision["source_policy"] = "local_knowledge"
        decision["local_knowledge"] = {
            "selected": True,
            "status": payload.get("status"),
            "reason": reason,
            "metrics": metrics,
            "evidence": payload,
        }
        return decision

    def _reject(self, decision: dict[str, Any], source: str, reason: str) -> dict[str, Any]:
        decision["rejected_sources"].append({"source": source, "reason": reason})
        decision[source] = {"selected": False, "status": "not_requested", "reason": reason}
        return decision

    def _external_source_required(self, knowledge_evaluation: dict[str, Any], intent: dict[str, Any]) -> bool:
        if bool(knowledge_evaluation.get("needs_web_search") or knowledge_evaluation.get("requires_external_information")):
            return True
        policy = intent.get("source_policy") if isinstance(intent.get("source_policy"), dict) else {}
        if str(policy.get("external_access") or "").lower() == "required":
            return True
        if bool(policy.get("requires_external_information") or policy.get("needs_web_search")):
            return True
        return False

    def _local_index_available(self, knowledge_status: dict[str, Any]) -> bool:
        try:
            return int(knowledge_status.get("chunk_count") or 0) > 0 or int(knowledge_status.get("embedding_count") or 0) > 0
        except Exception:
            return False

    def _passes_local_evidence_gate(self, text: str, payload: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
        metrics = {"top_score": 0.0, "lexical_overlap": 0.0, "citation_count": 0, "material_chars": 0}
        if not isinstance(payload, dict):
            return False, "local_probe_returned_invalid_payload", metrics
        if str(payload.get("status") or "") != "evidence_found":
            return False, str(payload.get("reason") or payload.get("status") or "local_evidence_not_found"), metrics

        score = self._top_score(payload)
        overlap = self._lexical_overlap(text, payload)
        citation_count = self._citation_count(payload)
        material_chars = len(self._material_text(payload))
        metrics.update({
            "top_score": round(score, 4),
            "lexical_overlap": round(overlap, 4),
            "citation_count": citation_count,
            "material_chars": material_chars,
        })

        # Evidence must be both retrieved and textually relevant.  Thresholds are
        # generic runtime confidence gates, not domain rules.  The citation gate
        # prevents hidden prompt injection without auditable retrieved chunks.
        if citation_count <= 0:
            return False, "local_evidence_has_no_citations", metrics
        if material_chars < 30:
            return False, "local_evidence_material_too_short", metrics
        if score < 0.30:
            return False, "local_evidence_score_below_threshold", metrics
        if overlap < 0.08:
            return False, "local_evidence_overlap_below_threshold", metrics
        return True, "local_knowledge_selected_by_evidence_gate", metrics

    def _top_score(self, payload: dict[str, Any]) -> float:
        try:
            results = payload.get("results") if isinstance(payload.get("results"), list) else []
            if not results:
                return 0.0
            return float((results[0] or {}).get("score") or 0.0)
        except Exception:
            return 0.0

    def _citation_count(self, payload: dict[str, Any]) -> int:
        citations = payload.get("citations") if isinstance(payload.get("citations"), list) else []
        if citations:
            return len(citations)
        results = payload.get("results") if isinstance(payload.get("results"), list) else []
        return len([item for item in results if isinstance(item, dict) and (item.get("text") or item.get("content") or item.get("chunk_text"))])

    def _material_text(self, payload: dict[str, Any]) -> str:
        material_parts: list[str] = []
        for key in ("answer", "answer_material"):
            if payload.get(key):
                material_parts.append(str(payload.get(key) or ""))
        for item in payload.get("results") if isinstance(payload.get("results"), list) else []:
            if isinstance(item, dict):
                material_parts.append(str(item.get("text") or item.get("content") or item.get("chunk_text") or ""))
        return "\n".join(material_parts)

    def _lexical_overlap(self, text: str, payload: dict[str, Any]) -> float:
        query_terms = self._terms(text)
        if not query_terms:
            return 0.0
        material_terms = self._terms(self._material_text(payload))
        if not material_terms:
            return 0.0
        return len(query_terms & material_terms) / max(1, len(query_terms))

    def _terms(self, text: str) -> set[str]:
        # Language-neutral tokenization only.  No domain/business routing words.
        raw = re.findall(r"[A-Za-z0-9_\-]{3,}|[\u4e00-\u9fff]{1,}|[\u3040-\u30ff]{2,}", str(text or "").lower())
        return {token for token in raw if token.strip()}
