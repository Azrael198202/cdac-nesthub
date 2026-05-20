from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
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
from ai_core.config.paths import RUNTIME_TRACES
from ai_core.utils.safe_json import safe_json_dumps, make_json_safe


@dataclass
class DeepSearchTrace:
    planned_queries: list[str]
    fetched_urls: list[str]
    extraction_layers: list[str]
    fact_count: int
    quality: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)




class DeepSearchWhiteboxTrace:
    """Append-only white-box trace for layered web evidence processing.

    The trace is intentionally generic. It records every extraction layer using
    runtime-neutral names and compact previews, so failed materialization can be
    diagnosed without exposing huge raw pages in normal responses.
    """

    def __init__(self, *, run_id: str = "", step_id: str = "", enabled: bool = True) -> None:
        self.run_id = run_id or "unknown_run"
        self.step_id = step_id or "unknown_step"
        self.enabled = enabled
        self.trace_id = f"deepsearch_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}_{uuid4().hex[:8]}"
        self.events: list[dict[str, Any]] = []
        self.path: Path | None = None
        if enabled:
            self.path = RUNTIME_TRACES / "deepsearch_whitebox" / str(self.run_id) / f"{self.trace_id}.jsonl"
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, *, stage: str, status: str, data: dict[str, Any] | None = None, reason: str = "") -> None:
        if not self.enabled:
            return
        event = {
            "trace_id": self.trace_id,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "at": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "status": status,
            "reason": reason,
            "data": self._compact(data or {}),
        }
        self.events.append(event)
        if self.path is not None:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(safe_json_dumps(event) + "\n")

    def summary(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "trace_id": self.trace_id,
            "run_id": self.run_id,
            "step_id": self.step_id,
            "trace_path": str(self.path) if self.path else "",
            "event_count": len(self.events),
            "stages": [str(e.get("stage")) for e in self.events],
            "failed_stages": [str(e.get("stage")) for e in self.events if str(e.get("status")) not in {"ok", "success", "skipped"}],
        }

    def _compact(self, value: Any, *, depth: int = 0) -> Any:
        if depth > 4:
            return {"truncated": "max_depth"}
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for idx, (k, v) in enumerate(value.items()):
                if idx >= 80:
                    out["truncated_items"] = len(value) - 80
                    break
                out[str(k)] = self._compact(v, depth=depth + 1)
            return out
        if isinstance(value, list):
            result = [self._compact(x, depth=depth + 1) for x in value[:80]]
            if len(value) > 80:
                result.append({"truncated_items": len(value) - 80})
            return result
        if isinstance(value, str):
            text = " ".join(value.split())
            if len(text) > 2200:
                return text[:2200] + " ...[truncated]"
            return text
        return make_json_safe(value)

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
        context = state.get("_execution_context") if isinstance(state.get("_execution_context"), dict) else {}
        run_id = str(context.get("run_id") or state.get("run_id") or "")
        step_id = str(context.get("step_id") or policy.get("step_id") or "")
        whitebox = DeepSearchWhiteboxTrace(run_id=run_id, step_id=step_id, enabled=bool(policy.get("deepsearch_whitebox_trace_enabled", True)))
        whitebox.record(stage="input", status="ok", data={"known": known, "objective_preview": objective[:300], "candidate_count": len(candidates), "policy_keys": sorted(str(k) for k in policy.keys())})
        ranked = self.ranker.rank(candidates=candidates, known=known, budget=budget)
        whitebox.record(stage="candidate_ranking", status="ok", data={"budget": getattr(budget, "__dict__", {}), "ranked_count": len(ranked), "ranked_preview": [self._candidate_preview(c) for c in ranked[:10]]})
        fetched: list[dict[str, Any]] = []
        urls: list[str] = []
        layers: list[str] = []
        reduced: dict[str, Any] = {}
        seen: set[str] = set()

        for candidate in ranked[: budget.max_fetches]:
            url = self._url(candidate)
            if not url or url in seen:
                whitebox.record(stage="candidate_skip", status="skipped", data={"candidate": self._candidate_preview(candidate), "url": url}, reason="empty_or_duplicate_url")
                continue
            seen.add(url)
            whitebox.record(stage="candidate_selected", status="ok", data={"candidate": self._candidate_preview(candidate), "url": url})
            browser_doc: dict[str, Any] | None = None
            if policy.get("browser_network_discovery_enabled", True):
                whitebox.record(stage="playwright_observation_start", status="ok", data={"url": url})
                observed = await self.browser_observer.observe(url=url)
                whitebox.record(stage="playwright_observation_result", status="success" if observed.status == "success" else "failed", data={"url": url, "status": observed.status, "final_url": observed.final_url, "title": observed.title, "visible_text_chars": len(observed.visible_text or ""), "html_chars": len(observed.html_excerpt or ""), "network_response_count": len(observed.network_responses), "structured_response_count": len([r for r in observed.network_responses if r.is_structured]), "console_count": len(observed.console_messages), "error": observed.error})
                if observed.status == "success":
                    browser_doc = observed.to_document()
                    browser_doc = self._materialize_browser_document(browser_doc=browser_doc, known=known, source_url=url, budget=budget, whitebox=whitebox)
                    whitebox.record(stage="browser_materialization_result", status="success" if browser_doc.get("normalized_facts") else "no_material", data={"url": browser_doc.get("url") or url, "layers": browser_doc.get("extraction_layers") or [], "fact_count": len(browser_doc.get("normalized_facts") or []), "answer_material_preview": str(browser_doc.get("answer_material") or "")[:1200], "quality": browser_doc.get("answer_material_quality") or {}})
                    urls.append(browser_doc.get("url") or url)
                    layers.extend(browser_doc.get("extraction_layers") or [])
                    # Do not let a rendered page snapshot short-circuit the pipeline
                    # unless it produced machine-structured or relation-preserving
                    # facts. Plain visible text remains only a later fallback.
                    if browser_doc.get("normalized_facts"):
                        fetched.append({"source": "browser_materialized_observation", "source_search_result": candidate, "document": browser_doc})
                        reduced = self.reducer.reduce(documents=fetched, known=known, state=state, budget=budget)
                        quality = reduced.get("answer_material_quality") if isinstance(reduced.get("answer_material_quality"), dict) else {}
                        whitebox.record(stage="reduction_after_browser_materialization", status="ok", data={"fact_count": len(reduced.get("normalized_facts") or []), "selected_block_count": len(reduced.get("selected_evidence_blocks") or []), "answer_material_preview": str(reduced.get("answer_material") or "")[:1200], "quality": quality})
                        if quality.get("passed") and self.budget_allocator.should_stop(normalized=reduced, fetched_count=len(fetched), budget=budget):
                            whitebox.record(stage="adaptive_stop", status="ok", data={"reason": "browser_materialized_evidence_passed", "fetched_count": len(fetched), "quality": quality})
                            break

            # DOM/text fallback is still useful when no structured network response
            # satisfies the evidence gate. It runs after browser observation.
            whitebox.record(stage="http_fetch_start", status="ok", data={"url": url})
            doc = await self.web.fetch(url=url, max_chars=max(policy.get("fetch_chars_per_source", budget.fetch_chars_per_source), budget.fetch_chars_per_source))
            whitebox.record(stage="http_fetch_result", status="success" if isinstance(doc, dict) and doc.get("status") == "success" else "failed", data={"url": url, "status": doc.get("status") if isinstance(doc, dict) else type(doc).__name__, "response_status": doc.get("response_status") if isinstance(doc, dict) else None, "title": doc.get("title") if isinstance(doc, dict) else "", "text_chars": len(str(doc.get("text_excerpt") or "")) if isinstance(doc, dict) else 0, "html_chars": len(str(doc.get("html_excerpt") or doc.get("raw_html") or "")) if isinstance(doc, dict) else 0, "error": doc.get("error") if isinstance(doc, dict) else ""})
            if not isinstance(doc, dict) or doc.get("status") != "success":
                continue
            if browser_doc:
                # Preserve browser-visible material and captured network metadata.
                doc = {**doc, **{k: v for k, v in browser_doc.items() if v}}
            extracted = self.extractor.extract(doc)
            whitebox.record(stage="generic_content_extraction", status="success", data={"url": url, "layers": extracted.get("extraction_layers") or [], "text_chars": len(str(extracted.get("text_excerpt") or "")), "table_count": len(extracted.get("tables") or []), "dom_block_count": len(extracted.get("dom_evidence_items") or [])})
            if browser_doc:
                extracted = self._merge_materialized_browser_doc(base=extracted, browser_doc=browser_doc)
                whitebox.record(stage="browser_http_merge", status="success", data={"url": url, "fact_count": len(extracted.get("normalized_facts") or []), "layers": extracted.get("extraction_layers") or [], "answer_material_preview": str(extracted.get("answer_material") or "")[:1200]})
            # Last structured fallback: generic temporal/numeric sequence parsing
            # over the already-rendered material. This is still structural, not a
            # task-specific text summary.
            if not extracted.get("normalized_facts"):
                visible_packet = "\n".join(str(x or "") for x in [
                    extracted.get("answer_material"), extracted.get("text_excerpt"), extracted.get("visible_text_excerpt")
                ])
                temporal = self.temporal_measurement_extractor.extract(text=visible_packet, known=known, source_url=url, max_rows=budget.fact_limit)
                whitebox.record(stage="temporal_sequence_extraction", status="success" if temporal.get("normalized_facts") else "no_material", data={"url": url, "fact_count": len(temporal.get("normalized_facts") or []), "answer_material_preview": str(temporal.get("answer_material") or "")[:1200], "quality": temporal.get("quality") or {}})
                if temporal.get("normalized_facts"):
                    extracted["normalized_facts"] = list(temporal.get("normalized_facts") or [])
                    extracted["answer_material"] = str(temporal.get("answer_material") or extracted.get("answer_material") or "")
                    extracted["answer_material_quality"] = temporal.get("quality") or extracted.get("answer_material_quality") or {}
                    extracted.setdefault("extraction_layers", []).append("temporal_measurement_sequence")
            urls.append(url)
            layers.extend(extracted.get("extraction_layers") or [])
            fetched.append({"source": "deep_web_extraction", "source_search_result": candidate, "document": extracted})
            reduced = self.reducer.reduce(documents=fetched, known=known, state=state, budget=budget)
            whitebox.record(stage="reduction_after_fallback", status="ok", data={"url": url, "fact_count": len(reduced.get("normalized_facts") or []), "selected_block_count": len(reduced.get("selected_evidence_blocks") or []), "answer_material_preview": str(reduced.get("answer_material") or "")[:1200], "quality": reduced.get("answer_material_quality") if isinstance(reduced.get("answer_material_quality"), dict) else {}})
            if self.budget_allocator.should_stop(normalized=reduced, fetched_count=len(fetched), budget=budget):
                whitebox.record(stage="adaptive_stop", status="ok", data={"reason": "fallback_evidence_passed", "fetched_count": len(fetched), "quality": reduced.get("answer_material_quality") if isinstance(reduced.get("answer_material_quality"), dict) else {}})
                break

        quality = reduced.get("answer_material_quality") if isinstance(reduced.get("answer_material_quality"), dict) else {}
        whitebox.record(stage="final_material", status="success" if reduced else "no_material", data={"fact_count": len(reduced.get("normalized_facts") or []) if isinstance(reduced, dict) else 0, "answer_material_preview": str(reduced.get("answer_material") or "")[:1600] if isinstance(reduced, dict) else "", "quality": quality})
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
                "deepsearch_whitebox_trace": whitebox.summary(),
            },
        }

    def _materialize_browser_document(self, *, browser_doc: dict[str, Any], known: dict[str, Any], source_url: str, budget: Any, whitebox: DeepSearchWhiteboxTrace | None = None) -> dict[str, Any]:
        layers: list[str] = ["browser_network_observation"]
        facts: list[dict[str, Any]] = []
        materials: list[str] = []
        source_summaries: list[dict[str, Any]] = []

        structured = self.structured_extractor.extract(browser_document=browser_doc, known=known, max_facts=budget.fact_limit)
        if whitebox:
            whitebox.record(stage="layer_1_network_json_xhr", status="success" if structured.normalized_facts else "no_material", data={"trace": structured.extraction_trace, "fact_count": len(structured.normalized_facts), "source_summary_count": len(structured.source_summaries), "material_preview": structured.answer_material[:1200]})
        if structured.normalized_facts:
            facts.extend(structured.normalized_facts)
            materials.append(structured.answer_material)
            source_summaries.extend(structured.source_summaries)
            layers.append("network_structured_response")
        browser_doc["structured_response_extraction"] = structured.extraction_trace

        embedded = self.embedded_structure_extractor.extract(document=browser_doc, known=known, max_facts=budget.fact_limit)
        if whitebox:
            whitebox.record(stage="layer_2_3_embedded_and_script_json", status="success" if embedded.normalized_facts else "no_material", data={"trace": embedded.extraction_trace, "fact_count": len(embedded.normalized_facts), "material_preview": embedded.answer_material[:1200]})
        if embedded.normalized_facts:
            facts.extend(embedded.normalized_facts)
            materials.append(embedded.answer_material)
            layers.append("embedded_machine_readable_structure")
        browser_doc["embedded_structure_extraction"] = embedded.extraction_trace

        relation = self.dom_relation_extractor.extract(document=browser_doc, known=known, max_facts=budget.fact_limit)
        if whitebox:
            whitebox.record(stage="layer_5_dom_table_relation", status="success" if relation.normalized_facts else "no_material", data={"trace": relation.extraction_trace, "fact_count": len(relation.normalized_facts), "material_preview": relation.answer_material[:1200]})
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

    def _candidate_preview(self, candidate: dict[str, Any]) -> dict[str, Any]:
        preview: dict[str, Any] = {}
        for key in ("url", "official_documentation_url", "title", "name", "snippet", "score", "source"):
            value = candidate.get(key)
            if value is not None:
                preview[key] = str(value)[:400]
        evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
        if evidence:
            preview["evidence_keys"] = sorted(str(k) for k in evidence.keys())[:30]
            for key in ("url", "title", "status", "response_status"):
                if key in evidence:
                    preview[f"evidence_{key}"] = str(evidence.get(key))[:300]
        return preview

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
