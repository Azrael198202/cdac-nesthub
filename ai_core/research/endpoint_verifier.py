from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from ai_core.config.paths import RUNTIME_TRACES


@dataclass
class EndpointCheck:
    url: str
    method: str
    status: str
    status_code: int | None
    content_type: str
    supports_json: bool
    requires_authentication: bool
    is_html: bool
    reason: str
    sample: str = ""


class EndpointVerifier:
    """Verify discovered network candidates with real HTTP responses.

    This class is deliberately domain-neutral. It does not know any provider,
    business category, or task type. It only verifies generic HTTP properties:
    status code, content type, JSON parseability, authentication requirement,
    and whether a candidate is actually an HTML page rather than a JSON API.
    """

    def __init__(self) -> None:
        self.trace_dir = RUNTIME_TRACES / "endpoint_checks"
        self.trace_dir.mkdir(parents=True, exist_ok=True)

    def verify_discovery(self, discovery: dict[str, Any]) -> dict[str, Any]:
        result = discovery.get("result") if isinstance(discovery.get("result"), dict) else {}
        urls = self._candidate_urls(discovery)
        checks = [self.verify_url(url) for url in urls[:8]]
        verified_json = next((check for check in checks if check.supports_json and check.status == "success"), None)
        html_candidate = next((check for check in checks if check.is_html and check.status in {"success", "html_page"}), None)

        recommendation = {
            "verified_json_api": verified_json is not None,
            "recommended_tool_type": "api" if verified_json else ("web_extract" if html_candidate else "external_solution_discovery"),
            "selected_verified_endpoint": asdict(verified_json) if verified_json else None,
            "selected_document_page": asdict(html_candidate) if html_candidate else None,
            "checks": [asdict(check) for check in checks],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        trace_id = "endpoint_check_" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        trace_path = self.trace_dir / f"{trace_id}.json"
        trace_payload = {"discovery_trace": discovery.get("trace_id"), "recommendation": recommendation}
        trace_path.write_text(json.dumps(trace_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        recommendation["trace_id"] = trace_id
        recommendation["trace_path"] = str(trace_path)

        result["runtime_endpoint_verification"] = recommendation
        discovery["result"] = result
        discovery["endpoint_verification"] = recommendation
        if discovery.get("status") == "success" and not recommendation["verified_json_api"]:
            # Keep discovery successful because useful evidence exists, but make
            # the executable strategy explicit so codegen does not invent JSON APIs.
            discovery["runtime_strategy"] = recommendation["recommended_tool_type"]
        return discovery

    def verify_url(self, url: str) -> EndpointCheck:
        url = str(url or "").strip()
        if not url:
            return EndpointCheck(url=url, method="GET", status="invalid", status_code=None, content_type="", supports_json=False, requires_authentication=False, is_html=False, reason="empty_url")
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "User-Agent": "GenericRuntimeEndpointVerifier/1.0",
                "Accept": "application/json,text/plain,text/html;q=0.8,*/*;q=0.5",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                status_code = int(getattr(response, "status", 0) or 0)
                content_type = str(response.headers.get("Content-Type", "")).lower()
                raw = response.read(120000)
        except urllib.error.HTTPError as exc:
            status_code = int(exc.code)
            content_type = str(exc.headers.get("Content-Type", "")).lower() if exc.headers else ""
            body = exc.read(4000) if hasattr(exc, "read") else b""
            return EndpointCheck(
                url=url,
                method="GET",
                status="authentication_required" if status_code in {401, 403} else "http_error",
                status_code=status_code,
                content_type=content_type,
                supports_json=False,
                requires_authentication=status_code in {401, 403},
                is_html="html" in content_type or self._looks_like_html(body),
                reason="authentication_required" if status_code in {401, 403} else f"http_error_{status_code}",
                sample=self._safe_sample(body),
            )
        except Exception as exc:
            return EndpointCheck(url=url, method="GET", status="error", status_code=None, content_type="", supports_json=False, requires_authentication=False, is_html=False, reason=str(exc))

        supports_json = self._is_json_response(content_type, raw)
        is_html = "html" in content_type or self._looks_like_html(raw)
        if supports_json:
            return EndpointCheck(url=url, method="GET", status="success", status_code=status_code, content_type=content_type, supports_json=True, requires_authentication=False, is_html=False, reason="json_verified", sample=self._safe_sample(raw))
        if is_html:
            return EndpointCheck(url=url, method="GET", status="html_page", status_code=status_code, content_type=content_type, supports_json=False, requires_authentication=False, is_html=True, reason="html_page_detected", sample=self._safe_sample(raw))
        return EndpointCheck(url=url, method="GET", status="unsupported", status_code=status_code, content_type=content_type, supports_json=False, requires_authentication=False, is_html=False, reason="non_json_response", sample=self._safe_sample(raw))

    def _candidate_urls(self, discovery: dict[str, Any]) -> list[str]:
        result = discovery.get("result") if isinstance(discovery.get("result"), dict) else {}
        docs = result.get("documentation_understanding") if isinstance(result.get("documentation_understanding"), dict) else {}
        selected = result.get("selected_candidate") if isinstance(result.get("selected_candidate"), dict) else {}
        urls: list[str] = []

        doc_url = str(selected.get("official_documentation_url") or "").strip()
        if doc_url:
            urls.append(doc_url)

        request_info = docs.get("request") if isinstance(docs.get("request"), dict) else {}
        for key in ("url", "endpoint", "base_url"):
            value = str(request_info.get(key) or "").strip()
            if not value:
                continue
            if value.startswith("http://") or value.startswith("https://"):
                urls.append(value)
            elif doc_url:
                urls.append(urllib.parse.urljoin(doc_url, value))

        for item in result.get("candidates", []) if isinstance(result.get("candidates"), list) else []:
            if isinstance(item, dict):
                url = str(item.get("official_documentation_url") or "").strip()
                if url:
                    urls.append(url)
                for evidence_url in item.get("evidence_urls", []) if isinstance(item.get("evidence_urls"), list) else []:
                    if str(evidence_url).strip():
                        urls.append(str(evidence_url).strip())

        for item in discovery.get("web_evidence", []) if isinstance(discovery.get("web_evidence"), list) else []:
            if isinstance(item, dict) and str(item.get("url") or "").strip():
                urls.append(str(item.get("url")).strip())

        seen: set[str] = set()
        output: list[str] = []
        for url in urls:
            normalized = self._normalize_url(url)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            output.append(normalized)
        return output

    def _normalize_url(self, url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return ""
        return urllib.parse.urlunparse(parsed)

    def _is_json_response(self, content_type: str, body: bytes) -> bool:
        sample = body[:120000].decode("utf-8", errors="ignore").strip()
        if "json" not in content_type and not sample.startswith(("{", "[")):
            return False
        try:
            json.loads(sample)
            return True
        except Exception:
            return False

    def _looks_like_html(self, body: bytes) -> bool:
        sample = body[:4000].decode("utf-8", errors="ignore").lower()
        return bool(re.search(r"<(html|head|body|script|div|table|meta|title)\b", sample))

    def _safe_sample(self, body: bytes) -> str:
        return body[:1000].decode("utf-8", errors="ignore").replace("\x00", "")
