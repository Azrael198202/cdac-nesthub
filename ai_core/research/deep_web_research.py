from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any

try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    BeautifulSoup = None  # type: ignore

try:
    import pandas as pd  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    pd = None  # type: ignore

try:
    import trafilatura  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    trafilatura = None  # type: ignore

from ai_core.research.web_research_tool import GenericWebResearchTool
from ai_core.runtime.evidence import EvidenceBudgetAllocator, CandidateEvidenceRanker, AdaptiveEvidenceReducer
from ai_core.runtime.browser import BrowserNetworkObserver, StructuredResponseExtractor, EmbeddedStructureExtractor, DomRelationExtractor
from ai_core.runtime.evidence.temporal_measurement_sequence import TemporalMeasurementSequenceExtractor


@dataclass
class DeepSearchTrace:
    planned_queries: list[str]
    fetched_urls: list[str]
    extraction_layers: list[str]
    fact_count: int
    quality: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WebContentExtractor:
    """Generic multi-layer web content extractor.

    Uses optional extraction libraries when installed, then falls back to a
    structural parser.  It does not embed domain/task keywords.
    """

    SKIP_TAGS = {"script", "style", "noscript", "svg", "canvas", "iframe"}

    def extract(self, document: dict[str, Any]) -> dict[str, Any]:
        html = str(document.get("html_excerpt") or document.get("raw_html") or document.get("sample") or "")
        visible = str(document.get("visible_text_excerpt") or document.get("text_excerpt") or "")
        layers: list[str] = []
        texts: list[str] = []
        tables: list[dict[str, Any]] = []
        dom_blocks: list[dict[str, Any]] = []

        if html and trafilatura is not None:
            try:
                extracted = trafilatura.extract(html, include_tables=True, include_comments=False)  # type: ignore[attr-defined]
                if extracted:
                    texts.append(extracted)
                    layers.append("trafilatura")
            except Exception:
                pass

        if html and BeautifulSoup is not None:
            try:
                soup = BeautifulSoup(html, "lxml")
            except Exception:
                soup = BeautifulSoup(html, "html.parser")
            for tag in soup.find_all(list(self.SKIP_TAGS)):
                try:
                    tag.decompose()
                except Exception:
                    pass
            main_text = " ".join(soup.get_text(" ").split())
            if main_text:
                texts.append(main_text)
                layers.append("beautifulsoup")
            for node in soup.find_all(["table", "tr", "li", "p", "section", "article", "div"]):
                text = " ".join(node.get_text(" ").split())
                if len(text) < 3:
                    continue
                attrs = {}
                for key in ("class", "id", "role", "aria-label"):
                    value = node.get(key)
                    if value:
                        attrs[key] = " ".join(value) if isinstance(value, list) else str(value)
                dom_blocks.append({"tag": getattr(node, "name", ""), "text": text[:1800], "attrs": attrs})
            layers.append("dom_blocks")

        if html and pd is not None:
            try:
                for table in pd.read_html(html):  # type: ignore[attr-defined]
                    rows = table.astype(str).values.tolist()
                    tables.append({"rows": rows[:80], "columns": [str(c) for c in table.columns][:40]})
                if tables:
                    layers.append("pandas_read_html")
            except Exception:
                pass

        existing_items = document.get("dom_evidence_items")
        if isinstance(existing_items, list):
            for item in existing_items:
                if isinstance(item, dict) and item.get("text"):
                    dom_blocks.append({"tag": item.get("tag", ""), "text": str(item.get("text"))[:1800], "attrs": {"class": item.get("class", "")}})
            if existing_items:
                layers.append("provided_dom_items")

        if visible:
            texts.append(visible)
            layers.append("visible_text")

        table_text = self._table_text(tables)
        if table_text:
            texts.insert(0, table_text)
        block_text = "\n".join(b["text"] for b in self._rank_blocks(dom_blocks)[:80])
        if block_text:
            texts.insert(0, block_text)

        return {
            "status": "success",
            "url": document.get("url", ""),
            "title": document.get("title", ""),
            "text_excerpt": "\n".join(self._dedupe_text(texts))[:24000],
            "visible_text_excerpt": visible,
            "dom_evidence_items": self._rank_blocks(dom_blocks)[:120],
            "tables": tables[:12],
            "extraction_layers": self._dedupe_text(layers),
        }

    def _table_text(self, tables: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for table in tables[:8]:
            columns = table.get("columns") if isinstance(table.get("columns"), list) else []
            if columns:
                lines.append(" | ".join(str(x) for x in columns[:30]))
            for row in table.get("rows", []) if isinstance(table.get("rows"), list) else []:
                if isinstance(row, list):
                    lines.append(" | ".join(str(x) for x in row[:30]))
        return "\n".join(lines)

    def _rank_blocks(self, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        scored: list[tuple[float, dict[str, Any]]] = []
        for block in blocks:
            text = str(block.get("text") or "")
            if not text:
                continue
            numeric = len(re.findall(r"[-+]?\d+(?:\.\d+)?", text))
            units = len(re.findall(r"\d\s*(?:°|%|mm|cm|km/h|mph|hPa|kPa|¥|\$|€)", text, flags=re.I))
            length_score = min(len(text) / 400, 3)
            repetition_penalty = 0.5 if len(set(text.split())) < max(2, len(text.split()) * 0.35) else 0
            score = numeric * 0.7 + units * 2.5 + length_score - repetition_penalty
            scored.append((score, block))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [b for _, b in scored]

    def _dedupe_text(self, values: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = " ".join(str(value or "").split())
            if not text:
                continue
            key = text[:500].casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(text)
        return out


class DeepWebResearchPipeline:
    """DeepSearch/DeepResearch-style web evidence pipeline.

    This pipeline performs query planning, candidate ranking, incremental page
    fetching, multi-layer extraction, reduction, and quality-controlled stopping.
    The expensive model should receive only compact normalized material.
    """

    def __init__(self) -> None:
        self.web = GenericWebResearchTool()
        self.extractor = WebContentExtractor()
        self.budget_allocator = EvidenceBudgetAllocator()
        self.ranker = CandidateEvidenceRanker()
        self.reducer = AdaptiveEvidenceReducer()
        self.browser_observer = BrowserNetworkObserver()
        self.structured_extractor = StructuredResponseExtractor()
        self.temporal_measurement_extractor = TemporalMeasurementSequenceExtractor()
        self.embedded_structure_extractor = EmbeddedStructureExtractor()
        self.dom_relation_extractor = DomRelationExtractor()

    async def run(
        self,
        *,
        candidates: list[dict[str, Any]],
        known: dict[str, Any],
        state: dict[str, Any],
        objective: str,
        policy: dict[str, Any],
    ) -> dict[str, Any]:
        budget = self.budget_allocator.allocate(known=known, objective=objective, candidates=candidates, policy=policy)
        ranked = self.ranker.rank(candidates=candidates, known=known, budget=budget)
        fetched: list[dict[str, Any]] = []
        urls: list[str] = []
        layers: list[str] = []
        reduced: dict[str, Any] = {}
        seen: set[str] = set()

        for candidate in ranked[: budget.max_fetches]:
            url = self._url(candidate)
            if not url or url in seen:
                continue
            seen.add(url)
            browser_doc: dict[str, Any] | None = None
            if policy.get("browser_network_discovery_enabled", True):
                observed = await self.browser_observer.observe(url=url)
                if observed.status == "success":
                    browser_doc = observed.to_document()
                    browser_doc = self._materialize_browser_document(browser_doc=browser_doc, known=known, source_url=url, budget=budget)
                    urls.append(browser_doc.get("url") or url)
                    layers.extend(browser_doc.get("extraction_layers") or [])
                    # Do not let a rendered page snapshot short-circuit the pipeline
                    # unless it produced machine-structured or relation-preserving
                    # facts. Plain visible text remains only a later fallback.
                    if browser_doc.get("normalized_facts"):
                        fetched.append({"source": "browser_materialized_observation", "source_search_result": candidate, "document": browser_doc})
                        reduced = self.reducer.reduce(documents=fetched, known=known, state=state, budget=budget)
                        quality = reduced.get("answer_material_quality") if isinstance(reduced.get("answer_material_quality"), dict) else {}
                        if quality.get("passed") and self.budget_allocator.should_stop(normalized=reduced, fetched_count=len(fetched), budget=budget):
                            break

            # DOM/text fallback is still useful when no structured network response
            # satisfies the evidence gate. It runs after browser observation.
            doc = await self.web.fetch(url=url, max_chars=max(policy.get("fetch_chars_per_source", budget.fetch_chars_per_source), budget.fetch_chars_per_source))
            if not isinstance(doc, dict) or doc.get("status") != "success":
                continue
            if browser_doc:
                # Preserve browser-visible material and captured network metadata.
                doc = {**doc, **{k: v for k, v in browser_doc.items() if v}}
            extracted = self.extractor.extract(doc)
            if browser_doc:
                extracted = self._merge_materialized_browser_doc(base=extracted, browser_doc=browser_doc)
            # Last structured fallback: generic temporal/numeric sequence parsing
            # over the already-rendered material. This is still structural, not a
            # task-specific text summary.
            if not extracted.get("normalized_facts"):
                visible_packet = "\n".join(str(x or "") for x in [
                    extracted.get("answer_material"), extracted.get("text_excerpt"), extracted.get("visible_text_excerpt")
                ])
                temporal = self.temporal_measurement_extractor.extract(text=visible_packet, known=known, source_url=url, max_rows=budget.fact_limit)
                if temporal.get("normalized_facts"):
                    extracted["normalized_facts"] = list(temporal.get("normalized_facts") or [])
                    extracted["answer_material"] = str(temporal.get("answer_material") or extracted.get("answer_material") or "")
                    extracted["answer_material_quality"] = temporal.get("quality") or extracted.get("answer_material_quality") or {}
                    extracted.setdefault("extraction_layers", []).append("temporal_measurement_sequence")
            urls.append(url)
            layers.extend(extracted.get("extraction_layers") or [])
            fetched.append({"source": "deep_web_extraction", "source_search_result": candidate, "document": extracted})
            reduced = self.reducer.reduce(documents=fetched, known=known, state=state, budget=budget)
            if self.budget_allocator.should_stop(normalized=reduced, fetched_count=len(fetched), budget=budget):
                break

        quality = reduced.get("answer_material_quality") if isinstance(reduced.get("answer_material_quality"), dict) else {}
        trace = DeepSearchTrace(
            planned_queries=self._queries_from_candidates(candidates),
            fetched_urls=urls,
            extraction_layers=sorted(set(str(x) for x in layers)),
            fact_count=len(reduced.get("normalized_facts") or []),
            quality=quality,
        )
        return {
            "status": "success" if reduced else "no_material",
            "data": {
                "normalized_facts": reduced.get("normalized_facts") or [],
                "structured_evidence": reduced.get("normalized_facts") or [],
                "selected_evidence_blocks": reduced.get("selected_evidence_blocks") or [],
                "answer_material": reduced.get("answer_material") or "",
                "answer_material_quality": quality,
                "source_summaries": reduced.get("source_summaries") or [],
                "raw_evidence_omitted": True,
                "deep_research_trace": trace.to_dict(),
            },
        }

    def _materialize_browser_document(self, *, browser_doc: dict[str, Any], known: dict[str, Any], source_url: str, budget: Any) -> dict[str, Any]:
        layers: list[str] = ["browser_network_observation"]
        facts: list[dict[str, Any]] = []
        materials: list[str] = []
        source_summaries: list[dict[str, Any]] = []

        structured = self.structured_extractor.extract(browser_document=browser_doc, known=known, max_facts=budget.fact_limit)
        if structured.normalized_facts:
            facts.extend(structured.normalized_facts)
            materials.append(structured.answer_material)
            source_summaries.extend(structured.source_summaries)
            layers.append("network_structured_response")
        browser_doc["structured_response_extraction"] = structured.extraction_trace

        embedded = self.embedded_structure_extractor.extract(document=browser_doc, known=known, max_facts=budget.fact_limit)
        if embedded.normalized_facts:
            facts.extend(embedded.normalized_facts)
            materials.append(embedded.answer_material)
            layers.append("embedded_machine_readable_structure")
        browser_doc["embedded_structure_extraction"] = embedded.extraction_trace

        relation = self.dom_relation_extractor.extract(document=browser_doc, known=known, max_facts=budget.fact_limit)
        if relation.normalized_facts:
            facts.extend(relation.normalized_facts)
            materials.append(relation.answer_material)
            layers.append("rendered_dom_relation")
        browser_doc["dom_relation_extraction"] = relation.extraction_trace

        facts = self._dedupe_facts(facts)[: budget.fact_limit]
        browser_doc["normalized_facts"] = facts
        browser_doc["structured_evidence"] = facts
        browser_doc["answer_material"] = self._join_materials(materials)
        browser_doc["source_summaries"] = source_summaries
        browser_doc["extraction_layers"] = sorted(set(layers))
        if facts:
            browser_doc["answer_material_quality"] = {
                "passed": True,
                "score": min(0.96, 0.64 + len(facts) * 0.015),
                "fact_count": len(facts),
                "source_level": "browser_materialized_structured_evidence",
                "raw_evidence_omitted": True,
                "domain_specific_rules_used": False,
            }
        return browser_doc

    def _merge_materialized_browser_doc(self, *, base: dict[str, Any], browser_doc: dict[str, Any]) -> dict[str, Any]:
        merged = {**base}
        for key in (
            "browser_network_responses", "structured_response_extraction",
            "embedded_structure_extraction", "dom_relation_extraction",
            "browser_observation",
        ):
            if browser_doc.get(key):
                merged[key] = browser_doc.get(key)
        facts = []
        for source in (browser_doc.get("normalized_facts"), base.get("normalized_facts")):
            if isinstance(source, list):
                facts.extend(x for x in source if isinstance(x, dict))
        facts = self._dedupe_facts(facts)
        if facts:
            merged["normalized_facts"] = facts
            merged["structured_evidence"] = facts
            merged["answer_material"] = self._join_materials([str(browser_doc.get("answer_material") or ""), str(base.get("answer_material") or "")])
            merged["answer_material_quality"] = browser_doc.get("answer_material_quality") or base.get("answer_material_quality") or {
                "passed": True,
                "score": min(0.95, 0.62 + len(facts) * 0.015),
                "fact_count": len(facts),
                "source_level": "browser_materialized_structured_evidence",
                "raw_evidence_omitted": True,
                "domain_specific_rules_used": False,
            }
        layers = []
        for source in (browser_doc.get("extraction_layers"), base.get("extraction_layers")):
            if isinstance(source, list):
                layers.extend(str(x) for x in source)
        merged["extraction_layers"] = sorted(set(layers))
        return merged

    def _dedupe_facts(self, facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for fact in facts:
            key = "|".join(str(fact.get(k, "")) for k in ("kind", "label", "value", "unit", "target", "context", "source_url"))[:900].casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(fact)
        return out

    def _join_materials(self, materials: list[str]) -> str:
        out: list[str] = []
        seen: set[str] = set()
        for material in materials:
            for line in str(material or "").splitlines():
                text = " ".join(line.split())
                if not text:
                    continue
                key = text.casefold()
                if key in seen:
                    continue
                seen.add(key)
                out.append(text)
        return "\n".join(out[:80])

    def _url(self, candidate: dict[str, Any]) -> str:
        for key in ("url", "official_documentation_url"):
            value = candidate.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return value
        evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
        for key in ("url", "official_documentation_url"):
            value = evidence.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return value
        return ""

    def _queries_from_candidates(self, candidates: list[dict[str, Any]]) -> list[str]:
        out: list[str] = []
        for c in candidates[:8]:
            q = " ".join(str(c.get(k) or "") for k in ("query", "title", "name", "snippet"))
            q = " ".join(q.split())
            if q and q not in out:
                out.append(q[:240])
        return out
