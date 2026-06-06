from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field, asdict
from typing import Any

from ai_core.runtime.environment import RuntimeDependencyManager


@dataclass
class ObservedNetworkResponse:
    url: str
    status: int | None = None
    method: str = ""
    resource_type: str = ""
    content_type: str = ""
    request_headers: dict[str, str] = field(default_factory=dict)
    response_headers: dict[str, str] = field(default_factory=dict)
    body_text: str = ""
    json_data: Any = None
    is_structured: bool = False
    requires_authentication: bool = False
    timing_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.body_text and len(self.body_text) > 12000:
            data["body_text"] = self.body_text[:12000]
            data["body_truncated"] = True
        return data


@dataclass
class BrowserObservationResult:
    url: str
    status: str
    final_url: str = ""
    title: str = ""
    visible_text: str = ""
    html_excerpt: str = ""
    network_responses: list[ObservedNetworkResponse] = field(default_factory=list)
    console_messages: list[str] = field(default_factory=list)
    error: str = ""
    dependency_recovery: dict[str, Any] | None = None

    def to_document(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "url": self.final_url or self.url,
            "title": self.title,
            "visible_text_excerpt": self.visible_text,
            "html_excerpt": self.html_excerpt,
            "browser_network_responses": [r.to_dict() for r in self.network_responses],
            "browser_console_messages": self.console_messages[:40],
            "browser_observation": {
                "mode": "playwright_cdp_network_observation",
                "network_response_count": len(self.network_responses),
                "structured_response_count": len([r for r in self.network_responses if r.is_structured]),
                "error": self.error,
                "dependency_recovery": self.dependency_recovery or {},
            },
        }


class BrowserNetworkObserver:
    """Browser observability layer based on Playwright/CDP-style network capture.

    The observer is domain-neutral. It does not know task semantics. It opens a
    page, captures the real browser network traffic, keeps JSON/API-like
    responses, and returns both structured responses and a DOM fallback snapshot.
    """

    API_LIKE_URL = re.compile(r"(?:/api/|/v\d+/|\.json(?:\?|$)|graphql|data|ajax|xhr|rpc|query)", re.I)
    STRUCTURED_CT = re.compile(r"(?:application|text)/(?:json|x-json|javascript)|\+json", re.I)
    AUTH_STATUS = {401, 403}

    def __init__(self, *, timeout_ms: int = 30000, max_body_chars: int = 250000, max_responses: int = 40) -> None:
        self.timeout_ms = timeout_ms
        self.max_body_chars = max_body_chars
        self.max_responses = max_responses

    async def observe(self, *, url: str, wait_until: str = "domcontentloaded", run_id: str = "") -> BrowserObservationResult:
        dependency_result: dict[str, Any] | None = None
        try:
            from playwright.async_api import async_playwright  # type: ignore
        except Exception:
            repaired = await RuntimeDependencyManager(run_id=run_id or "browser_observation").ensure(
                "playwright_browser",
                context={"reason": "import_unavailable", "url": url},
            )
            dependency_result = repaired.to_dict()
            try:
                from playwright.async_api import async_playwright  # type: ignore
            except Exception as exc:  # pragma: no cover - optional runtime dependency
                return BrowserObservationResult(
                    url=url,
                    status="unavailable",
                    error=f"playwright_unavailable_after_repair: {exc}",
                    dependency_recovery=dependency_result,
                )

        responses: list[ObservedNetworkResponse] = []
        console_messages: list[str] = []
        browser = None
        try:
            async with async_playwright() as p:
                try:
                    browser = await p.chromium.launch(headless=True)
                except Exception as launch_exc:
                    repaired = await RuntimeDependencyManager(run_id=run_id or "browser_observation").ensure(
                        "playwright_browser",
                        context={"reason": "launch_failed", "url": url, "error": str(launch_exc)},
                    )
                    dependency_result = repaired.to_dict()
                    browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(ignore_https_errors=True)
                page = await context.new_page()

                page.on("console", lambda msg: console_messages.append(str(msg.text)[:500]))

                async def on_response(response: Any) -> None:
                    if len(responses) >= self.max_responses:
                        return
                    try:
                        request = response.request
                        response_url = str(response.url)
                        content_type = str(response.headers.get("content-type", ""))
                        status = int(response.status)
                        resource_type = str(getattr(request, "resource_type", "") or "")
                        keep = self._should_keep(response_url=response_url, content_type=content_type, resource_type=resource_type)
                        if not keep and status not in self.AUTH_STATUS:
                            return
                        body_text = ""
                        json_data: Any = None
                        is_structured = False
                        try:
                            body_text = await response.text()
                            if len(body_text) > self.max_body_chars:
                                body_text = body_text[: self.max_body_chars]
                        except Exception:
                            body_text = ""
                        if body_text:
                            parsed = self._try_parse_json(body_text)
                            if parsed is not None:
                                json_data = parsed
                                is_structured = True
                            elif self.STRUCTURED_CT.search(content_type):
                                is_structured = True
                        responses.append(ObservedNetworkResponse(
                            url=response_url,
                            status=status,
                            method=str(request.method),
                            resource_type=resource_type,
                            content_type=content_type,
                            request_headers={str(k): str(v) for k, v in dict(request.headers).items()},
                            response_headers={str(k): str(v) for k, v in dict(response.headers).items()},
                            body_text=body_text,
                            json_data=json_data,
                            is_structured=is_structured,
                            requires_authentication=status in self.AUTH_STATUS,
                        ))
                    except Exception:
                        return

                page.on("response", lambda response: asyncio.create_task(on_response(response)))
                await page.goto(url, wait_until=wait_until, timeout=self.timeout_ms)
                try:
                    await page.wait_for_load_state("networkidle", timeout=min(self.timeout_ms, 15000))
                except Exception:
                    pass
                # Give late XHR/fetch a brief chance to arrive without blocking too long.
                await page.wait_for_timeout(800)
                title = ""
                visible = ""
                html = ""
                final_url = str(page.url)
                try:
                    title = await page.title()
                except Exception:
                    pass
                try:
                    visible = " ".join((await page.locator("body").inner_text(timeout=3000)).split())[:30000]
                except Exception:
                    pass
                try:
                    html = (await page.content())[:50000]
                except Exception:
                    pass
                await context.close()
                await browser.close()
                return BrowserObservationResult(
                    url=url,
                    status="success",
                    final_url=final_url,
                    title=title,
                    visible_text=visible,
                    html_excerpt=html,
                    network_responses=self._dedupe_responses(responses),
                    console_messages=list(dict.fromkeys(console_messages))[:40],
                    dependency_recovery=dependency_result,
                )
        except Exception as exc:
            try:
                if browser is not None:
                    await browser.close()
            except Exception:
                pass
            return BrowserObservationResult(url=url, status="error", error=str(exc), dependency_recovery=dependency_result)

    def _should_keep(self, *, response_url: str, content_type: str, resource_type: str) -> bool:
        if self.STRUCTURED_CT.search(content_type):
            return True
        if resource_type in {"xhr", "fetch"}:
            return True
        if self.API_LIKE_URL.search(response_url):
            return True
        return False

    def _try_parse_json(self, text: str) -> Any:
        try:
            return json.loads(text)
        except Exception:
            return None

    def _dedupe_responses(self, responses: list[ObservedNetworkResponse]) -> list[ObservedNetworkResponse]:
        out: list[ObservedNetworkResponse] = []
        seen: set[str] = set()
        for r in responses:
            key = f"{r.method}:{r.status}:{r.url}:{str(r.body_text)[:200]}"
            if key in seen:
                continue
            seen.add(key)
            out.append(r)
        return out[: self.max_responses]
