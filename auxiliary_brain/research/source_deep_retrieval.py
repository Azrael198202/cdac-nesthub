from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse


FetchCallable = Callable[..., Awaitable[dict[str, Any]]]


@dataclass
class SourceDeepRetrievalConfig:
    max_depth_per_uri: int = 2
    max_child_uri_per_page: int = 10
    max_total_uri_per_engine: int = 30
    max_fetch_chars: int = 12000


class SourceDeepRetrievalExplorer:
    """Generic contract-driven URI deep retrieval.

    The explorer never decides that a page type is good or bad.  It repeatedly
    fetches candidate URIs, evaluates the accumulated material against the
    output contract, and only stops when the contract is satisfied or the depth,
    URI, or time budget is exhausted.  Search-result pages, navigation pages,
    documentation pages, list pages, and article/detail pages are all treated as
    ordinary URI material; usefulness is determined by relevance, evidence
    support, consistency, and requested output fields.
    """

    def __init__(self, *, composer: Any, config: SourceDeepRetrievalConfig | None = None) -> None:
        self.composer = composer
        self.config = config or SourceDeepRetrievalConfig()

    async def explore(
        self,
        *,
        user_input: str,
        search_payload: dict[str, Any],
        fetcher: FetchCallable,
        source_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        policy = source_policy if isinstance(source_policy, dict) else {}
        config = SourceDeepRetrievalConfig(
            max_depth_per_uri=self._safe_int(policy.get("max_depth_per_uri"), self.config.max_depth_per_uri),
            max_child_uri_per_page=self._safe_int(policy.get("max_child_uri_per_page"), self.config.max_child_uri_per_page),
            max_total_uri_per_engine=self._safe_int(policy.get("max_total_uri_per_engine"), self.config.max_total_uri_per_engine),
            max_fetch_chars=self._safe_int(policy.get("max_fetch_chars"), self.config.max_fetch_chars),
        )
        results = search_payload.get("results") if isinstance(search_payload.get("results"), list) else []
        queue: list[dict[str, Any]] = []
        for rank, item in enumerate(results, start=1):
            if not isinstance(item, dict):
                continue
            url = self._clean(item.get("url"))
            if not self._safe_http_url(url):
                continue
            queue.append({"url": url, "depth": 0, "parent_url": "", "rank": rank, "origin": "search_result", "anchor_text": item.get("title") or item.get("snippet") or ""})
        visited: set[str] = set()
        fetched_docs: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        best_composed: dict[str, Any] = {}
        while queue and len(visited) < max(1, config.max_total_uri_per_engine):
            node = queue.pop(0)
            url = self._canonical_url(node.get("url"))
            if not url or url in visited:
                continue
            visited.add(url)
            depth = self._safe_int(node.get("depth"), 0)
            doc = await fetcher(url=url, max_chars=max(1000, config.max_fetch_chars))
            if not isinstance(doc, dict):
                events.append({"stage": "fetch", "status": "error", "url": url, "depth": depth, "reason": "fetcher_returned_non_dict"})
                continue
            doc = dict(doc)
            doc.setdefault("url", url)
            doc["retrieval_depth"] = depth
            doc["retrieval_parent_url"] = node.get("parent_url") or ""
            if doc.get("status") == "success":
                fetched_docs.append(doc)
                composed = self._compose(user_input=user_input, search_payload=search_payload, fetched_docs=fetched_docs)
                best_composed = composed if isinstance(composed, dict) else best_composed
                events.append({
                    "stage": "evaluate_uri_material",
                    "status": "passed" if composed.get("status") == "completed" else "not_satisfied",
                    "url": url,
                    "depth": depth,
                    "item_count": (composed.get("synthesis") or {}).get("item_count") if isinstance(composed.get("synthesis"), dict) else None,
                    "validation_errors": (composed.get("synthesis") or {}).get("validation_errors") if isinstance(composed.get("synthesis"), dict) else [],
                })
                if composed.get("status") == "completed" and composed.get("answer"):
                    return {
                        "status": "success",
                        "fetched_documents": fetched_docs,
                        "answer": str(composed.get("answer") or ""),
                        "composed": composed,
                        "visited_urls": list(visited),
                        "events": events,
                        "stop_reason": "output_contract_satisfied",
                    }
                if depth < max(0, config.max_depth_per_uri):
                    children = self._rank_child_links(
                        user_input=user_input,
                        parent_url=url,
                        links=doc.get("discovered_links") if isinstance(doc.get("discovered_links"), list) else [],
                    )
                    added = 0
                    for child in children:
                        child_url = self._canonical_url(child.get("url"))
                        if not child_url or child_url in visited or any(self._canonical_url(x.get("url")) == child_url for x in queue):
                            continue
                        queue.append({
                            "url": child_url,
                            "depth": depth + 1,
                            "parent_url": url,
                            "origin": "child_uri",
                            "anchor_text": child.get("anchor_text") or child.get("title") or "",
                        })
                        added += 1
                        if added >= max(0, config.max_child_uri_per_page):
                            break
                    events.append({"stage": "expand_child_uri", "status": "ok", "url": url, "depth": depth, "added": added})
            else:
                events.append({"stage": "fetch", "status": "error", "url": url, "depth": depth, "reason": str(doc.get("error") or "fetch_failed")[:400]})
        return {
            "status": "exhausted",
            "fetched_documents": fetched_docs,
            "answer": str(best_composed.get("answer") or "") if isinstance(best_composed, dict) else "",
            "composed": best_composed,
            "visited_urls": list(visited),
            "events": events,
            "stop_reason": "depth_or_uri_budget_exhausted",
        }

    def _compose(self, *, user_input: str, search_payload: dict[str, Any], fetched_docs: list[dict[str, Any]]) -> dict[str, Any]:
        evidence = {
            "original_user_input": user_input,
            "results": search_payload.get("results") if isinstance(search_payload.get("results"), list) else [],
            "fetched_documents": fetched_docs,
        }
        execution = {"status": "completed", "execution_mode": "web_search", "capability": "web_retrieval", "answer_material": "", "evidence": evidence}
        materials = [{
            "source": "source_deep_retrieval",
            "status": "completed",
            "answer_material": "",
            "evidence": evidence,
            "content": {"evidence": evidence, "results": evidence["results"], "fetched_documents": fetched_docs},
        }]
        state = {"original_input": user_input, "execution": execution}
        return self.composer.compose(state=state, materials=materials)

    def _rank_child_links(self, *, user_input: str, parent_url: str, links: list[dict[str, Any]]) -> list[dict[str, Any]]:
        terms = self._query_terms(user_input)
        parent_host = urlparse(parent_url).netloc.casefold()
        ranked: list[tuple[tuple[int, int, int], dict[str, Any]]] = []
        for link in links[:200]:
            if not isinstance(link, dict):
                continue
            url = self._canonical_url(link.get("url"))
            if not self._safe_http_url(url):
                continue
            parsed = urlparse(url)
            text = self._clean(" ".join(str(link.get(k) or "") for k in ("anchor_text", "title", "url"))).casefold()
            term_hits = sum(1 for term in terms if term and term.casefold() in text)
            same_host = 1 if parsed.netloc.casefold() == parent_host else 0
            path_depth = len([p for p in parsed.path.split("/") if p])
            # Prefer relevant links, then same host, then deeper concrete paths.
            ranked.append(((term_hits, same_host, min(path_depth, 8)), link))
        ranked.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in ranked]

    def _query_terms(self, text: str) -> list[str]:
        stop = {
            "the", "and", "for", "with", "from", "that", "this", "please", "provide", "give", "show", "latest", "today",
            "each", "story", "item", "title", "summary", "brief", "source", "publication", "time", "url", "link",
        }
        terms: list[str] = []
        for token in re.findall(r"[A-Za-z0-9_+.#/-]{3,}|[\u3040-\u30ff\u3400-\u9fff]{2,}", str(text or "")):
            clean = token.strip(" .,:;()[]{}<>\\\"'`")
            if not clean or clean.casefold() in stop:
                continue
            if clean not in terms:
                terms.append(clean)
            if len(terms) >= 12:
                break
        return terms

    def _canonical_url(self, value: Any) -> str:
        url = self._clean(value)
        if not url:
            return ""
        return url.split("#", 1)[0]

    def _safe_http_url(self, value: str) -> bool:
        try:
            parsed = urlparse(str(value or ""))
            return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
        except Exception:
            return False

    def _clean(self, value: Any) -> str:
        return " ".join(str(value or "").split()).strip()

    def _safe_int(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return default
