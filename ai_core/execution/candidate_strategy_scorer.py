from __future__ import annotations

from dataclasses import asdict
from typing import Any

from auxiliary_brain.research.endpoint_verifier import EndpointVerifier, EndpointCheck
from ai_core.utils.safe_json import make_json_safe


class CandidateStrategyScorer:
    """Score API/Web/browser extraction candidates with real light verification.

    The scorer is domain-neutral. It does not know what the capability means.
    It only checks generic properties of candidate URLs and metadata, then
    recommends one of:
      - json_api
      - html_extract
      - browser_extract
      - skip
    """

    def __init__(self) -> None:
        self.endpoint_verifier = EndpointVerifier()

    def score_candidates(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        scored: list[dict[str, Any]] = []
        for index, candidate in enumerate(candidates, start=1):
            if not isinstance(candidate, dict):
                continue
            scored.append(self.score_candidate(candidate, index=index))
        return sorted(scored, key=lambda item: (-float(item.get("score", 0)), int(item.get("rank") or 9999)))

    def score_candidate(self, candidate: dict[str, Any], *, index: int = 0) -> dict[str, Any]:
        url = str(candidate.get("url") or candidate.get("official_documentation_url") or "").strip()
        check: EndpointCheck | None = None
        if url.startswith(("http://", "https://")):
            try:
                check = self.endpoint_verifier.verify_url(url)
            except Exception as exc:
                check = None
                candidate = {**candidate, "light_verification_error": str(exc)}

        score = 0.0
        reasons: list[str] = []
        tool_type = "skip"

        requires_key = bool(candidate.get("requires_api_key") or candidate.get("requires_authentication"))
        supports_json_declared = bool(candidate.get("supports_json"))
        candidate_text = " ".join(str(candidate.get(k) or "") for k in ("name", "title", "url", "official_documentation_url", "notes")).lower()
        evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
        evidence_text = str(evidence.get("text_excerpt") or evidence.get("snippet") or evidence.get("sample") or "").lower()
        looks_like_doc_page = any(marker in candidate_text for marker in ("api", "docs", "documentation", "developers"))
        key_markers = ("api key", "your_api_key", "appid", "requires api key", "sign up", "get api key")
        if any(marker in candidate_text or marker in evidence_text for marker in key_markers):
            requires_key = True

        if check is not None:
            if check.supports_json and check.status == "success":
                score += 100
                tool_type = "json_api"
                reasons.append("verified_json_response")
            elif check.is_html and check.status_code and 200 <= check.status_code < 400:
                score += 70
                tool_type = self._html_tool_type(check)
                reasons.append("verified_html_page")
            elif check.requires_authentication:
                score -= 60
                reasons.append("authentication_required")
            elif check.status == "error":
                score -= 20
                reasons.append("verification_error")
            else:
                score += 5
                reasons.append(check.reason or "verified_non_json")

            if check.status_code and 200 <= check.status_code < 400:
                score += 20
                reasons.append("http_success")
            if check.status_code in {401, 403}:
                score -= 50
        else:
            if supports_json_declared:
                score += 25
                tool_type = "json_api"
                reasons.append("json_declared_not_verified")
            elif url:
                score += 15
                tool_type = "html_extract"
                reasons.append("url_available_not_verified")

        if requires_key:
            score -= 80
            reasons.append("api_key_required")
        else:
            score += 25
            reasons.append("no_api_key_required_or_not_detected")
        if looks_like_doc_page and tool_type in {"html_extract", "browser_extract"}:
            score -= 35
            reasons.append("documentation_page_not_data_endpoint")
        if str(candidate.get("source") or "") in {"web_evidence", "documentation_evidence"}:
            score += 10
            reasons.append("evidence_based_candidate")
        if candidate.get("evidence"):
            score += 10
            reasons.append("has_page_evidence")
        if not url:
            score -= 100
            reasons.append("missing_url")
            tool_type = "skip"

        return make_json_safe({
            **candidate,
            "candidate_index": index,
            "tool_type": tool_type,
            "score": round(score, 2),
            "score_reasons": reasons,
            "light_verification": asdict(check) if check is not None else None,
        })

    def _html_tool_type(self, check: EndpointCheck) -> str:
        sample = (check.sample or "").lower()
        dynamic_markers = ["__next", "nuxt", "react", "vue", "cloudflare", "captcha", "enable javascript"]
        if any(marker in sample for marker in dynamic_markers):
            return "browser_extract"
        return "html_extract"
