from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


def json_safe_string(value: Any) -> str:
    try:
        import json
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(value)

from .query_planner import SearchQueryPlanner
from .query_verification import SearchQueryVerificationGate

try:  # Optional dependency path. Core still works without these packages.
    from bs4 import BeautifulSoup  # type: ignore
except Exception:  # pragma: no cover - optional import
    BeautifulSoup = None  # type: ignore


@dataclass(frozen=True)
class EvidenceChunk:
    source_url: str
    source_title: str
    source_type: str
    text: str
    relevance_score: float
    trust_score: float
    purpose: str
    fingerprint: str


class WebEvidenceOptimizer:
    """Optimize noisy web/retrieval material into compact evidence packs.

    The optimizer is generic infrastructure. It never chooses a concrete
    business feature and never executes external material. Its job is to:
    query-plan, clean, chunk, deduplicate, score, extract evidence hints, and
    preserve provenance so small local models receive short structured context.
    """

    MAX_CHUNK_CHARS = 900
    MIN_CHUNK_CHARS = 80
    DEFAULT_BATCH_SIZE = 8
    DEFAULT_BATCH_TOP_K = 3
    DEFAULT_MAX_EVIDENCE_ITEMS = 5
    DEFAULT_EVIDENCE_TOKEN_BUDGET = 1800

    def __init__(self) -> None:
        self.query_planner = SearchQueryPlanner()
        self.query_verification_gate = SearchQueryVerificationGate()

    def plan_queries(self, *, user_input: str, capability: str = "", objective: str = "", known: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return self.query_planner.plan(user_input=user_input, capability=capability, objective=objective, known=known)

    def verify_query_plan(self, *, query: str, user_input: str, objective: str = "", source_contract: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.query_verification_gate.verify_and_rewrite(query=query, user_input=user_input, objective=objective, source_contract=source_contract)

    def optimize(
        self,
        *,
        user_input: str,
        search_results: list[dict[str, Any]] | None = None,
        documents: list[dict[str, Any]] | None = None,
        capability: str = "",
        objective: str = "",
        known: dict[str, Any] | None = None,
        max_items: int = 5,
        batch_size: int | None = None,
        batch_top_k: int | None = None,
        token_budget: int | None = None,
    ) -> dict[str, Any]:
        known = known if isinstance(known, dict) else {}
        planned_queries = self.plan_queries(user_input=user_input, capability=capability, objective=objective, known=known)
        query_text = " ".join([user_input or "", capability or "", objective or "", " ".join(q.get("query", "") for q in planned_queries)])
        query_terms = self._terms(query_text)
        raw_docs = self._materialize_documents(search_results or [], documents or [])
        chunks = self._build_chunks(raw_docs, query_terms=query_terms)
        chunks = self._dedupe_chunks(chunks)
        batch_size = int(batch_size or self.DEFAULT_BATCH_SIZE)
        batch_top_k = int(batch_top_k or self.DEFAULT_BATCH_TOP_K)
        selected_chunks = self._batch_select_chunks(chunks, batch_size=batch_size, batch_top_k=batch_top_k, max_items=max_items or self.DEFAULT_MAX_EVIDENCE_ITEMS)
        evidence_pack = [self._chunk_to_pack_item(c) for c in selected_chunks]
        evidence_pack = self._limit_evidence_pack(evidence_pack, token_budget=int(token_budget or self.DEFAULT_EVIDENCE_TOKEN_BUDGET), max_items=max_items or self.DEFAULT_MAX_EVIDENCE_ITEMS)
        status = "verified" if evidence_pack else "no_usable_evidence"
        return {
            "status": status,
            "planned_queries": planned_queries,
            "evidence_pack": evidence_pack,
            "summary": self._summary(evidence_pack),
            "optimizer_report": {
                "raw_search_result_count": len(search_results or []),
                "raw_document_count": len(documents or []),
                "chunk_count_after_dedupe": len(chunks),
                "batch_size": batch_size,
                "batch_top_k": batch_top_k,
                "selected_evidence_count": len(evidence_pack),
                "token_budget_estimate": int(token_budget or self.DEFAULT_EVIDENCE_TOKEN_BUDGET),
                "optional_packages": {
                    "beautifulsoup4_available": BeautifulSoup is not None,
                    "advanced_reranker_configured": False,
                },
                "domain_specific_rules_used": False,
            },
        }

    def _materialize_documents(self, search_results: list[dict[str, Any]], documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        by_url: dict[str, dict[str, Any]] = {}
        for item in search_results:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            by_url[url] = {
                "url": url,
                "title": str(item.get("title") or ""),
                "snippet": str(item.get("snippet") or ""),
                "text": str(item.get("snippet") or item.get("title") or ""),
            }
        for wrapper in documents:
            if not isinstance(wrapper, dict):
                continue
            doc = wrapper.get("document") if isinstance(wrapper.get("document"), dict) else wrapper
            result = wrapper.get("source_search_result") if isinstance(wrapper.get("source_search_result"), dict) else {}
            url = str(doc.get("url") or result.get("url") or "").strip()
            if not url:
                continue
            text = "\n".join(str(x or "") for x in [
                doc.get("title") or result.get("title"),
                doc.get("text_excerpt"),
                doc.get("visible_text_excerpt"),
                doc.get("dom_evidence_text"),
                result.get("snippet"),
            ])
            by_url[url] = {
                "url": url,
                "title": str(doc.get("title") or result.get("title") or ""),
                "snippet": str(result.get("snippet") or ""),
                "text": self._clean_text(text),
            }
        output.extend(by_url.values())
        return output

    def _build_chunks(self, docs: list[dict[str, Any]], *, query_terms: list[str]) -> list[EvidenceChunk]:
        chunks: list[EvidenceChunk] = []
        for doc in docs:
            url = str(doc.get("url") or "")
            title = str(doc.get("title") or url)
            text = self._clean_text(str(doc.get("text") or doc.get("snippet") or title))
            if not text:
                continue
            for part in self._split_text(text):
                if len(part) < self.MIN_CHUNK_CHARS:
                    continue
                relevance = self._score(part, query_terms)
                trust = self._trust_score(url)
                if relevance < 0.05 and trust < 0.45:
                    continue
                chunks.append(EvidenceChunk(
                    source_url=url,
                    source_title=title[:180],
                    source_type=self._source_type(url),
                    text=part[: self.MAX_CHUNK_CHARS],
                    relevance_score=round(relevance, 4),
                    trust_score=round(trust, 4),
                    purpose=self._purpose(part),
                    fingerprint=self._fingerprint(part),
                ))
        return chunks

    def _batch_select_chunks(self, chunks: list[EvidenceChunk], *, batch_size: int, batch_top_k: int, max_items: int) -> list[EvidenceChunk]:
        """Select top evidence in small batches, then perform a global top-k.

        This keeps tiny local models from receiving large noisy web payloads.
        Scoring stays deterministic and domain-neutral.
        """
        if not chunks:
            return []
        batch_size = max(1, min(int(batch_size or self.DEFAULT_BATCH_SIZE), 24))
        batch_top_k = max(1, min(int(batch_top_k or self.DEFAULT_BATCH_TOP_K), batch_size))
        max_items = max(1, min(int(max_items or self.DEFAULT_MAX_EVIDENCE_ITEMS), 12))
        locally_selected: list[EvidenceChunk] = []
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            ranked = sorted(batch, key=lambda c: (c.relevance_score + c.trust_score * 0.35), reverse=True)[:batch_top_k]
            locally_selected.extend(ranked)
        return sorted(locally_selected, key=lambda c: (c.relevance_score + c.trust_score * 0.35), reverse=True)[:max_items]

    def _limit_evidence_pack(self, evidence_pack: list[dict[str, Any]], *, token_budget: int, max_items: int) -> list[dict[str, Any]]:
        """Limit evidence size before it is passed to a small model.

        Token count is approximated by chars/4 so the function remains dependency-free.
        """
        token_budget = max(200, int(token_budget or self.DEFAULT_EVIDENCE_TOKEN_BUDGET))
        max_items = max(1, int(max_items or self.DEFAULT_MAX_EVIDENCE_ITEMS))
        output: list[dict[str, Any]] = []
        used = 0
        for item in evidence_pack[:max_items]:
            cloned = dict(item)
            excerpt = str(cloned.get("evidence_excerpt") or "")
            facts = cloned.get("extracted_facts") if isinstance(cloned.get("extracted_facts"), list) else []
            hints = cloned.get("implementation_hints") if isinstance(cloned.get("implementation_hints"), list) else []
            notes = cloned.get("security_notes") if isinstance(cloned.get("security_notes"), list) else []
            static_chars = len(json_safe_string(facts)) + len(json_safe_string(hints)) + len(json_safe_string(notes)) + 120
            remaining_chars = max(0, (token_budget - used) * 4 - static_chars)
            if remaining_chars <= 0:
                break
            cloned["evidence_excerpt"] = excerpt[: min(len(excerpt), remaining_chars, 700)]
            used += max(1, (len(str(cloned.get("evidence_excerpt") or "")) + static_chars) // 4)
            output.append(cloned)
            if used >= token_budget:
                break
        return output

    def _dedupe_chunks(self, chunks: list[EvidenceChunk]) -> list[EvidenceChunk]:
        seen: set[str] = set()
        output: list[EvidenceChunk] = []
        for chunk in sorted(chunks, key=lambda c: c.relevance_score + c.trust_score, reverse=True):
            if chunk.fingerprint in seen:
                continue
            seen.add(chunk.fingerprint)
            output.append(chunk)
        return output

    def _chunk_to_pack_item(self, chunk: EvidenceChunk) -> dict[str, Any]:
        return {
            "source_url": chunk.source_url,
            "source_title": chunk.source_title,
            "source_type": chunk.source_type,
            "relevance_score": chunk.relevance_score,
            "trust_score": chunk.trust_score,
            "trusted": chunk.trust_score >= 0.65 or chunk.source_type in {"official_doc", "standards_or_reference"},
            "purpose": chunk.purpose,
            "extracted_facts": self._extract_facts(chunk.text),
            "implementation_hints": self._extract_hints(chunk.text),
            "security_notes": self._extract_security_notes(chunk.text),
            "evidence_excerpt": chunk.text[:700],
            "provenance": {"url": chunk.source_url, "title": chunk.source_title, "fingerprint": chunk.fingerprint},
        }

    def _summary(self, evidence_pack: list[dict[str, Any]]) -> dict[str, Any]:
        hosts = []
        for item in evidence_pack:
            host = urlparse(str(item.get("source_url") or "")).netloc
            if host and host not in hosts:
                hosts.append(host)
        trusted_count = sum(1 for item in evidence_pack if item.get("trusted"))
        return {
            "source_count": len(hosts),
            "trusted_item_count": trusted_count,
            "top_hosts": hosts[:6],
            "ready_for_small_model": bool(evidence_pack),
        }

    def _clean_text(self, text: str) -> str:
        raw = str(text or "")
        raw = re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", raw, flags=re.I | re.S)
        if "<" in raw and ">" in raw and BeautifulSoup is not None:
            try:
                soup = BeautifulSoup(raw, "html.parser")
                self._remove_known_noise_nodes(soup)
                selected = self._select_content_nodes(soup)
                raw = selected if selected else soup.get_text(" ")
            except Exception:
                pass
        text = re.sub(r"\s+", " ", raw).strip()
        return text

    def _remove_known_noise_nodes(self, soup: Any) -> None:
        # Deterministic web boilerplate removal. Generic page-structure words only;
        # no task/domain vocabulary is used here.
        for tag in ["script", "style", "nav", "footer", "header", "aside", "form", "noscript", "svg", "iframe", "menu"]:
            for node in list(soup.find_all(tag)):
                try:
                    node.decompose()
                except Exception:
                    pass
        noise_re = re.compile(r"(^|[-_\s])(nav|menu|footer|header|sidebar|breadcrumb|cookie|ads?|advert|promo)([-_\s]|$)", re.I)
        for node in list(soup.find_all(True)):
            try:
                values: list[str] = []
                node_id = node.get("id")
                if node_id:
                    values.append(str(node_id))
                classes = node.get("class")
                if isinstance(classes, list):
                    values.extend(str(x) for x in classes)
                elif classes:
                    values.append(str(classes))
                if values and noise_re.search(" ".join(values)):
                    node.decompose()
            except Exception:
                pass

    def _select_content_nodes(self, soup: Any) -> str:
        preferred_texts: list[str] = []
        containers = soup.find_all(["main", "article"]) or []
        if not containers:
            containers = soup.find_all(["section"]) or []
        search_roots = containers or [soup]
        for root in search_roots:
            for node in root.find_all(["p", "li", "pre", "code", "table"]):
                try:
                    value = node.get_text(" ", strip=True)
                except Exception:
                    value = ""
                if value and len(value) >= 20:
                    preferred_texts.append(value)
        if preferred_texts:
            return " ".join(preferred_texts)
        for node in soup.find_all(["main", "article", "section"]):
            try:
                value = node.get_text(" ", strip=True)
            except Exception:
                value = ""
            if value and len(value) >= 40:
                preferred_texts.append(value)
        return " ".join(preferred_texts)

    def _split_text(self, text: str) -> list[str]:
        text = self._clean_text(text)
        if len(text) <= self.MAX_CHUNK_CHARS:
            return [text]
        sentences = re.split(r"(?<=[。.!?])\s+|\n+", text)
        chunks: list[str] = []
        current = ""
        for sentence in sentences:
            if not sentence:
                continue
            if len(current) + len(sentence) + 1 > self.MAX_CHUNK_CHARS:
                if current:
                    chunks.append(current.strip())
                current = sentence
            else:
                current = (current + " " + sentence).strip()
        if current:
            chunks.append(current.strip())
        return chunks[:24]

    def _terms(self, text: str) -> list[str]:
        raw = re.findall(r"[A-Za-z0-9][A-Za-z0-9_+./:-]{1,40}|[\u3040-\u30ff\u3400-\u9fff]{2,}", str(text or "").casefold())
        stop = {"the", "and", "for", "with", "from", "that", "this", "runtime", "capability", "implementation", "validation", "verification", "schema", "policy", "official", "documentation", "example"}
        return [t for t, _ in Counter(x for x in raw if x not in stop).most_common(24)]

    def _score(self, text: str, query_terms: list[str]) -> float:
        if not query_terms:
            return 0.1
        hay = str(text or "").casefold()
        hits = sum(1 for term in query_terms if term and term in hay)
        density = hits / max(len(query_terms), 1)
        signal_bonus = 0.0
        for token in ["api", "parameter", "configuration", "security", "authentication", "example", "usage", "standard", "library", "reference"]:
            if token in hay:
                signal_bonus += 0.025
        return min(1.0, density * 0.85 + signal_bonus)

    def _trust_score(self, url: str) -> float:
        host = urlparse(str(url or "")).netloc.casefold()
        if not host:
            return 0.25
        score = 0.45
        if host.endswith(".gov") or host.endswith(".edu"):
            score += 0.25
        if any(part in host for part in ["docs.", "developer", "github.com", "pypi.org", "readthedocs", "python.org", "ietf.org", "w3.org"]):
            score += 0.22
        if host.count(".") <= 2:
            score += 0.05
        if any(part in host for part in ["spam", "coupon", "mirror"]):
            score -= 0.25
        return max(0.0, min(1.0, score))

    def _source_type(self, url: str) -> str:
        host = urlparse(str(url or "")).netloc.casefold()
        if any(x in host for x in ["python.org", "ietf.org", "w3.org", "docs.", "developer"]):
            return "official_doc"
        if "github.com" in host or "gitlab" in host:
            return "source_repository"
        if "pypi.org" in host or "readthedocs" in host:
            return "package_or_documentation"
        if host.endswith(".gov") or host.endswith(".edu"):
            return "standards_or_reference"
        return "web_page"

    def _purpose(self, text: str) -> str:
        low = str(text or "").casefold()
        if any(x in low for x in ["security", "credential", "secret", "authentication", "permission"]):
            return "security_validation"
        if any(x in low for x in ["example", "usage", "sample", "quickstart"]):
            return "implementation_example"
        if any(x in low for x in ["api", "reference", "documentation", "parameters"]):
            return "official_documentation"
        return "general_evidence"

    def _extract_facts(self, text: str) -> list[str]:
        facts = []
        for sentence in re.split(r"(?<=[。.!?])\s+", str(text or "")):
            if any(tok in sentence.casefold() for tok in ["must", "required", "supports", "uses", "provides", "parameter", "configuration"]):
                facts.append(sentence[:220])
            if len(facts) >= 5:
                break
        return facts

    def _extract_hints(self, text: str) -> list[str]:
        hints = []
        for sentence in re.split(r"(?<=[。.!?])\s+", str(text or "")):
            if any(tok in sentence.casefold() for tok in ["import", "example", "usage", "function", "class", "library", "standard"]):
                hints.append(sentence[:220])
            if len(hints) >= 5:
                break
        return hints

    def _extract_security_notes(self, text: str) -> list[str]:
        notes = []
        for sentence in re.split(r"(?<=[。.!?])\s+", str(text or "")):
            if any(tok in sentence.casefold() for tok in ["secret", "password", "credential", "tls", "ssl", "token", "permission", "sandbox"]):
                notes.append(sentence[:220])
            if len(notes) >= 5:
                break
        return notes

    def _fingerprint(self, text: str) -> str:
        normalized = re.sub(r"\W+", " ", str(text or "").casefold()).strip()[:600]
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
