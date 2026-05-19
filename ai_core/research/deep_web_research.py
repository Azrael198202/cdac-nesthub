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
from ai_core.runtime.browser import BrowserNetworkObserver, StructuredResponseExtractor


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
                    structured = self.structured_extractor.extract(browser_document=browser_doc, known=known, max_facts=budget.fact_limit)
                    browser_doc["normalized_facts"] = structured.normalized_facts
                    browser_doc["answer_material"] = structured.answer_material
                    browser_doc["source_summaries"] = structured.source_summaries
                    browser_doc["structured_response_extraction"] = structured.extraction_trace
                    urls.append(browser_doc.get("url") or url)
                    layers.append("browser_network_observation")
                    if structured.normalized_facts:
                        layers.append("structured_network_response")
                    fetched.append({"source": "browser_network_discovery", "source_search_result": candidate, "document": browser_doc})
                    reduced = self.reducer.reduce(documents=fetched, known=known, state=state, budget=budget)
                    if self.budget_allocator.should_stop(normalized=reduced, fetched_count=len(fetched), budget=budget):
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
            if browser_doc and browser_doc.get("browser_network_responses"):
                extracted["browser_network_responses"] = browser_doc.get("browser_network_responses")
                extracted["structured_response_extraction"] = browser_doc.get("structured_response_extraction")
                extracted["normalized_facts"] = browser_doc.get("normalized_facts") or []
                extracted["answer_material"] = browser_doc.get("answer_material") or ""
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
