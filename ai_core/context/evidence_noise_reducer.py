from __future__ import annotations

import re
from typing import Any

from ai_core.codegen.runtime_variable_inferencer import RuntimeVariableInferencer


class EvidenceNoiseReducer:
    """Domain-neutral evidence cleaner and selector.

    The reducer turns large discovery/search payloads into a compact evidence
    packet before any LLM code-generation or answer-synthesis step. It scores
    each evidence item by dynamic runtime constraints only: whether the text
    covers required parameter values, whether the source is fetchable, whether
    it appears to be a real data page rather than an example/doc page, and a
    bounded confidence score. It does not contain business vocabulary.
    """

    DEFAULT_MAX_ITEMS = 4
    DEFAULT_MAX_TEXT_PER_ITEM = 1800
    DEFAULT_MIN_CONFIDENCE = 0.45

    NOISE_MARKERS = (
        "privacy policy", "terms of use", "cookie", "advertising", "newsletter",
        "sign in", "login", "subscribe", "all rights reserved", "copyright",
        "download app", "careers", "contact us", "site map",
    )
    EXAMPLE_MARKERS = (
        "example", "sample", "your_api_key", "demo", "placeholder",
        "appid", "api key", "curl ", "swagger", "openapi",
    )


    def reduce(self, payload: dict[str, Any], *, known_parameters: dict[str, Any] | None = None, max_items: int | None = None, max_chars_per_item: int | None = None) -> dict[str, Any]:
        """Generic compact evidence reducer used by role-scoped prompts.

        It accepts a small wrapper payload containing arbitrary evidence items
        and returns only the highest-scoring items according to dynamic runtime
        parameters.
        """
        max_items = max_items or self.DEFAULT_MAX_ITEMS
        max_chars_per_item = max_chars_per_item or self.DEFAULT_MAX_TEXT_PER_ITEM
        constraints = {k: self._aliases(v) for k, v in (known_parameters or {}).items()}
        if not constraints:
            constraints = self.extract_required_terms(payload)
        raw_items = payload.get("evidence") if isinstance(payload, dict) else []
        discovery_like = {"documentation_evidence": raw_items if isinstance(raw_items, list) else []}
        items = self.extract_evidence_items(discovery_like)
        scored = [self.score_evidence_item(item, constraints=constraints, max_text_per_item=max_chars_per_item) for item in items]
        scored = [x for x in scored if x.get("confidence", 0) >= self.DEFAULT_MIN_CONFIDENCE or x.get("coverage", {}).get("passed")]
        scored.sort(key=lambda x: (x.get("coverage", {}).get("coverage_ratio", 0), x.get("confidence", 0), -int(x.get("rank", 9999))), reverse=True)
        selected = scored[:max_items]
        return {
            "known_parameters": known_parameters or {},
            "selection_policy": {
                "coverage_required": True,
                "min_confidence": self.DEFAULT_MIN_CONFIDENCE,
                "max_items": max_items,
                "max_chars_per_item": max_chars_per_item,
            },
            "selected_evidence": selected,
            "dropped_evidence_count": max(0, len(items) - len(selected)),
        }

    def compact_generation_request(self, request: dict[str, Any], *, max_items: int | None = None, max_text_per_item: int | None = None) -> dict[str, Any]:
        if not isinstance(request, dict):
            return {}
        max_items = max_items or self.DEFAULT_MAX_ITEMS
        max_text_per_item = max_text_per_item or self.DEFAULT_MAX_TEXT_PER_ITEM
        constraints = self.extract_required_terms(request)
        compact = {
            "request_type": request.get("request_type"),
            "capability": request.get("capability"),
            "step": self._compact_step(request.get("step") or request.get("source_step")),
            "user_input": self._truncate(str(request.get("user_input") or ""), 800),
            "runtime_request_semantics": self._compact_semantics(request.get("runtime_request_semantics") or {}),
            "constraints": self._compact_constraints(request.get("constraints") or {}),
            "expected_contract": request.get("expected_contract"),
        }
        for key in ("runtime_fallback", "api_discovery", "external_solution_discovery"):
            value = request.get(key)
            if key == "runtime_fallback" and isinstance(value, dict):
                compact[key] = {
                    "reason": value.get("reason"),
                    "recommended_tool_type": value.get("recommended_tool_type"),
                    "endpoint_verification": self._compact_endpoint_verification(value.get("endpoint_verification") or {}),
                    "failed_verification_summary": self._compact_failed_verification(value.get("failed_verification") or {}),
                }
            elif key == "api_discovery" and isinstance(value, dict):
                compact[key] = self.compact_discovery(value, constraints=constraints, max_items=max_items, max_text_per_item=max_text_per_item)
            elif key == "external_solution_discovery" and isinstance(value, dict):
                compact[key] = self.compact_discovery(value, constraints=constraints, max_items=max_items, max_text_per_item=max_text_per_item)
        runtime_variable_contract = RuntimeVariableInferencer().infer(request)
        compact["runtime_variables"] = runtime_variable_contract.get("runtime_variables", [])
        compact["parameterization_policy"] = runtime_variable_contract.get("parameterization_policy", {})
        compact["evidence_selection_policy"] = {
            "coverage_required": True,
            "min_confidence": self.DEFAULT_MIN_CONFIDENCE,
            "max_items": max_items,
            "max_text_per_item": max_text_per_item,
            "selected_by": "runtime_parameter_coverage_and_noise_filter",
        }
        return compact

    def compact_discovery(self, discovery: dict[str, Any], *, constraints: dict[str, list[str]] | None = None, max_items: int | None = None, max_text_per_item: int | None = None) -> dict[str, Any]:
        constraints = constraints or self.extract_required_terms(discovery)
        max_items = max_items or self.DEFAULT_MAX_ITEMS
        max_text_per_item = max_text_per_item or self.DEFAULT_MAX_TEXT_PER_ITEM
        items = self.extract_evidence_items(discovery)
        scored = [self.score_evidence_item(item, constraints=constraints, max_text_per_item=max_text_per_item) for item in items]
        scored = [x for x in scored if x.get("confidence", 0) >= self.DEFAULT_MIN_CONFIDENCE or x.get("coverage", {}).get("passed")]
        scored.sort(key=lambda x: (x.get("coverage", {}).get("coverage_ratio", 0), x.get("confidence", 0), -int(x.get("rank", 9999))), reverse=True)
        selected = scored[:max_items]
        result = discovery.get("result") if isinstance(discovery.get("result"), dict) else {}
        return {
            "status": discovery.get("status"),
            "strategy_used": discovery.get("strategy_used"),
            "runtime_strategy": discovery.get("runtime_strategy"),
            "selected_candidate": self._compact_candidate(result.get("selected_candidate") if isinstance(result.get("selected_candidate"), dict) else {}),
            "endpoint_verification": self._compact_endpoint_verification(discovery.get("endpoint_verification") or result.get("runtime_endpoint_verification") or {}),
            "selected_evidence": selected,
            "dropped_evidence_count": max(0, len(items) - len(selected)),
        }

    def extract_required_terms(self, value: Any) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        def visit(obj: Any):
            if isinstance(obj, dict):
                for key in ("known", "known_parameters", "parameters"):
                    v = obj.get(key)
                    if isinstance(v, dict):
                        for kk, vv in v.items():
                            if kk in {"optional", "context", "source_step"}:
                                continue
                            aliases = self._aliases(vv)
                            if aliases:
                                out.setdefault(str(kk), [])
                                out[str(kk)].extend(a for a in aliases if a not in out[str(kk)])
                for k, v in obj.items():
                    if k in {"documentation_evidence", "web_evidence", "documents", "web_results", "checks", "sample", "text_excerpt"}:
                        continue
                    if isinstance(v, (dict, list)):
                        visit(v)
            elif isinstance(obj, list):
                for x in obj[:20]:
                    visit(x)
        visit(value)
        return out

    def extract_evidence_items(self, discovery: dict[str, Any]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        def add(url: str, title: str, text: str, source: str, rank: int, status: Any = None):
            if not url and not text:
                return
            items.append({"url": url, "title": title, "text": text, "source": source, "rank": rank, "status": status})
        for base_key in ("documentation_evidence", "web_evidence"):
            for i, item in enumerate(discovery.get(base_key) or [], start=1):
                if not isinstance(item, dict):
                    continue
                doc = item.get("document") if isinstance(item.get("document"), dict) else {}
                search = item.get("source_search_result") if isinstance(item.get("source_search_result"), dict) else item
                url = str(doc.get("url") or search.get("url") or "")
                title = str(doc.get("title") or search.get("title") or "")
                text = "\n".join(str(x or "") for x in (title, search.get("snippet"), doc.get("text_excerpt"), search.get("text_excerpt")))
                add(url, title, text, base_key, i, doc.get("response_status") or search.get("response_status"))
        for base_key in ("documents", "web_results"):
            for i, item in enumerate(discovery.get(base_key) or [], start=100):
                if not isinstance(item, dict):
                    continue
                doc = item.get("document") if isinstance(item.get("document"), dict) else {}
                search = item.get("source_search_result") if isinstance(item.get("source_search_result"), dict) else item
                url = str(doc.get("url") or item.get("url") or search.get("url") or "")
                title = str(doc.get("title") or item.get("title") or search.get("title") or "")
                text = "\n".join(str(x or "") for x in (title, item.get("snippet"), search.get("snippet"), doc.get("text_excerpt")))
                add(url, title, text, base_key, i, doc.get("response_status") or item.get("response_status"))
        result = discovery.get("result") if isinstance(discovery.get("result"), dict) else {}
        ev = result.get("runtime_endpoint_verification") if isinstance(result.get("runtime_endpoint_verification"), dict) else discovery.get("endpoint_verification")
        if isinstance(ev, dict):
            selected_page = ev.get("selected_document_page") if isinstance(ev.get("selected_document_page"), dict) else {}
            if selected_page:
                add(str(selected_page.get("url") or ""), "selected_document_page", str(selected_page.get("sample") or ""), "endpoint_verification", 0, selected_page.get("status_code"))
        return items

    def score_evidence_item(self, item: dict[str, Any], *, constraints: dict[str, list[str]], max_text_per_item: int) -> dict[str, Any]:
        raw_text = str(item.get("text") or "")
        clean = self.clean_text(raw_text)
        lower = clean.lower()
        matched: dict[str, list[str]] = {}
        missing = []
        for key, aliases in constraints.items():
            if key in {"detail", "details", "detail_level", "semantic_modifiers", "format", "language", "locale", "unit", "units", "timezone", "date_expression"}:
                continue
            found = [a for a in aliases if a and a.lower() in lower]
            if found:
                matched[key] = found[:5]
            else:
                missing.append(key)
        required_count = len(matched) + len(missing)
        coverage_ratio = (len(matched) / required_count) if required_count else 1.0
        noise_hits = [m for m in self.NOISE_MARKERS if m in lower]
        example_like = any(m in lower for m in self.EXAMPLE_MARKERS)
        status = item.get("status")
        confidence = 0.25 + coverage_ratio * 0.55
        if status and str(status).startswith("2"):
            confidence += 0.1
        if item.get("url"):
            confidence += 0.05
        if noise_hits:
            confidence -= min(0.2, 0.03 * len(noise_hits))
        if example_like and coverage_ratio < 1.0:
            confidence -= 0.2
        confidence = max(0.0, min(1.0, confidence))
        return {
            "url": item.get("url"),
            "title": self._truncate(str(item.get("title") or ""), 180),
            "source": item.get("source"),
            "rank": item.get("rank"),
            "confidence": round(confidence, 3),
            "coverage": {"passed": coverage_ratio >= 0.75, "coverage_ratio": round(coverage_ratio, 3), "matched": matched, "missing": missing},
            "noise": {"noise_markers": noise_hits[:5], "example_like": example_like},
            "text_excerpt": self._truncate(clean, max_text_per_item),
        }

    def clean_text(self, text: str) -> str:
        text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", str(text or ""))
        text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
        text = re.sub(r"(?is)<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        # Keep the windows around dynamic parameter matches while dropping long site boilerplate.
        parts = []
        for sentence in re.split(r"(?<=[.!?。；;])\s+", text):
            s = sentence.strip()
            if not s:
                continue
            low = s.lower()
            if len(s) < 240 and not any(m in low for m in self.NOISE_MARKERS):
                parts.append(s)
            if len(" ".join(parts)) > 6000:
                break
        return " ".join(parts) if parts else text[:6000]

    def _compact_step(self, step: Any) -> dict[str, Any]:
        if not isinstance(step, dict):
            return {}
        return {k: step.get(k) for k in ("step_id", "task_id", "step_type", "task_type", "action", "objective", "parameters", "required_capability", "execution_ready") if k in step}

    def _compact_semantics(self, sem: dict[str, Any]) -> dict[str, Any]:
        return {k: sem.get(k) for k in ("original_user_input", "objective", "action", "task_type", "known_parameters", "optional_parameters", "runtime_constraints", "output_preferences") if k in sem}

    def _compact_constraints(self, constraints: dict[str, Any]) -> dict[str, Any]:
        keys = ["force_runtime_strategy", "must_return_schema_compatible_output", "must_define_run_payload_entrypoint", "no_mock_data", "must_use_real_network_when_external_data_is_required", "must_not_assume_json_api_when_endpoint_verification_failed"]
        return {k: constraints.get(k) for k in keys if k in constraints}

    def _compact_endpoint_verification(self, ev: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(ev, dict):
            return {}
        checks = []
        for c in ev.get("checks") or []:
            if isinstance(c, dict):
                checks.append({k: c.get(k) for k in ("url", "status", "status_code", "content_type", "supports_json", "requires_authentication", "is_html", "reason")})
        return {
            "verified_json_api": ev.get("verified_json_api"),
            "recommended_tool_type": ev.get("recommended_tool_type"),
            "selected_verified_endpoint": ev.get("selected_verified_endpoint"),
            "selected_document_page": {k: (ev.get("selected_document_page") or {}).get(k) for k in ("url", "status", "status_code", "content_type", "supports_json", "requires_authentication", "reason")},
            "checks": checks[:6],
        }

    def _compact_failed_verification(self, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        return {"status": value.get("status"), "reason": value.get("reason"), "checks": [{"name": c.get("name"), "result": self._truncate(str(c.get("result") or c), 500)} for c in (value.get("checks") or [])[:4] if isinstance(c, dict)]}

    def _compact_candidate(self, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        return {k: value.get(k) for k in ("name", "url", "official_documentation_url", "requires_api_key", "supports_json", "selection_reason") if k in value}

    def _aliases(self, value: Any) -> list[str]:
        values: list[str] = []
        def add(v: Any):
            if v is None:
                return
            if isinstance(v, dict):
                for vv in v.values(): add(vv)
                return
            if isinstance(v, (list, tuple, set)):
                for vv in v: add(vv)
                return
            s = str(v).strip()
            if not s:
                return
            values.append(s)
            m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
            if m:
                y, mo, d = m.groups()
                values.extend([f"{int(mo)}/{int(d)}", f"{mo}/{d}", f"{mo}-{d}", f"{int(d)}", f"{int(d)} May" if mo == "05" else f"{int(mo)}/{int(d)}"])
        add(value)
        dedup = []
        for v in values:
            if v and v not in dedup:
                dedup.append(v)
        return dedup[:12]

    def _truncate(self, text: str, n: int) -> str:
        text = str(text or "")
        return text if len(text) <= n else text[:n] + "...[truncated]"
