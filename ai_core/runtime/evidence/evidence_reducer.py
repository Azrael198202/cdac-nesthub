from __future__ import annotations

from typing import Any

from .evidence_budget import EvidenceBudget
from .evidence_normalizer import RuntimeEvidenceNormalizer


class AdaptiveEvidenceReducer:
    """Reduce raw evidence to compact structured material.

    This layer avoids hard truncation. It normalizes every fetched source, merges
    facts, deduplicates blocks, and returns only compact facts/material for later
    model calls. It remains domain-neutral: runtime variables and generic
    structure drive the selection.
    """

    def __init__(self) -> None:
        self.normalizer = RuntimeEvidenceNormalizer()

    def reduce(
        self,
        *,
        documents: list[dict[str, Any]],
        known: dict[str, Any],
        state: dict[str, Any] | None,
        budget: EvidenceBudget,
    ) -> dict[str, Any]:
        facts: list[dict[str, Any]] = []
        blocks: list[str] = []
        materials: list[str] = []
        source_summaries: list[dict[str, Any]] = []
        qualities: list[dict[str, Any]] = []
        seen_fact: set[str] = set()
        seen_block: set[str] = set()

        for doc in documents:
            if not isinstance(doc, dict):
                continue
            document = doc.get("document") if isinstance(doc.get("document"), dict) else doc
            source_url = str(document.get("url") or doc.get("url") or "")
            text = self._document_text(document)
            normalized = self.normalizer.normalize(text=text, known=known, source_url=source_url, state=state or {})
            quality = normalized.get("answer_material_quality") if isinstance(normalized.get("answer_material_quality"), dict) else {}
            qualities.append(quality)
            for fact in normalized.get("normalized_facts") or []:
                if not isinstance(fact, dict):
                    continue
                key = self._fact_key(fact)
                if key in seen_fact:
                    continue
                seen_fact.add(key)
                facts.append(fact)
                if len(facts) >= budget.fact_limit:
                    break
            for block in normalized.get("selected_evidence_blocks") or []:
                text_block = " ".join(str(block).split())
                if not text_block:
                    continue
                key = text_block.casefold()
                if key in seen_block:
                    continue
                seen_block.add(key)
                blocks.append(text_block[:900])
                if len(blocks) >= budget.block_limit:
                    break
            material = str(normalized.get("answer_material") or "").strip()
            if material:
                materials.append(material)
            source_summaries.append({
                "url": source_url,
                "title": document.get("title"),
                "quality": quality,
                "fact_count": len(normalized.get("normalized_facts") or []),
            })

        compact_material = self._compact_material(materials=materials, facts=facts, blocks=blocks, budget=budget)
        quality = self._merged_quality(qualities=qualities, facts=facts, blocks=blocks, budget=budget)
        return {
            "normalized_facts": facts[: budget.fact_limit],
            "selected_evidence_blocks": blocks[: budget.block_limit],
            "answer_material": compact_material,
            "answer_material_quality": quality,
            "source_summaries": source_summaries,
            "raw_evidence_omitted": True,
            "reduction_strategy": "adaptive_structured_evidence_reduction",
        }

    def _document_text(self, document: dict[str, Any]) -> str:
        parts: list[str] = []
        for key in (
            "visible_text_excerpt", "text_excerpt", "dom_evidence_text",
            "html_excerpt", "snippet", "sample", "title",
        ):
            value = document.get(key)
            if isinstance(value, str):
                parts.append(value)
        items = document.get("dom_evidence_items")
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
        return "\n".join(parts)

    def _fact_key(self, fact: dict[str, Any]) -> str:
        return "|".join(str(fact.get(k, "")) for k in ("kind", "label", "value", "unit", "target", "context")).casefold()[:600]

    def _compact_material(self, *, materials: list[str], facts: list[dict[str, Any]], blocks: list[str], budget: EvidenceBudget) -> str:
        lines: list[str] = []
        if facts:
            for fact in facts[: min(len(facts), 16)]:
                value = str(fact.get("value") or "").strip()
                unit = str(fact.get("unit") or "").strip()
                label = str(fact.get("label") or fact.get("kind") or "value").strip()
                target = str(fact.get("target") or "").strip()
                context = str(fact.get("context") or "").strip()
                line = " | ".join(x for x in [target, label, (value + unit).strip(), context[:220]] if x)
                if line:
                    lines.append(line)
        if not lines:
            lines.extend(materials[:6])
        if not lines:
            lines.extend(blocks[:6])
        compact = []
        seen: set[str] = set()
        for line in lines:
            text = " ".join(str(line).split())
            key = text.casefold()
            if text and key not in seen:
                seen.add(key)
                compact.append(text)
        return "\n".join(compact)[: budget.llm_material_chars]

    def _merged_quality(self, *, qualities: list[dict[str, Any]], facts: list[dict[str, Any]], blocks: list[str], budget: EvidenceBudget) -> dict[str, Any]:
        scores = [float(q.get("score") or 0) for q in qualities if isinstance(q, dict)]
        score = max(scores) if scores else 0.0
        if facts:
            score = max(score, min(0.95, 0.45 + len(facts) * 0.035))
        return {
            "passed": bool(facts or blocks),
            "score": round(score, 3),
            "fact_count": len(facts),
            "block_count": len(blocks),
            "source_quality_count": len(qualities),
            "raw_evidence_omitted": True,
            "domain_specific_rules_used": False,
            "budget": budget.to_dict(),
        }
