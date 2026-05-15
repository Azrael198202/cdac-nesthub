from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import html
import re


@dataclass
class BrowserFetchResult:
    """Result returned by a browser-capable document fetch operation."""

    url: str
    status: str
    visible_text: str = ""
    markup_excerpt: str = ""
    attribute_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_evidence(self) -> dict[str, Any]:
        return {
            "source": "browser_document",
            "status": self.status,
            "url": self.url,
            "text_excerpt": self.visible_text,
            "html_excerpt": self.markup_excerpt,
            "dom_evidence_text": self.attribute_text,
            "metadata": self.metadata,
        }


class BrowserRuntimeAdapter:
    """Domain-neutral browser evidence adapter.

    It is intentionally protocol-oriented. If Playwright is available at runtime,
    the caller may provide a rendered document. In tests or constrained runtime,
    static markup can be supplied directly. This class avoids domain-specific
    selectors and extracts generic visible text plus informative DOM attributes.
    """

    INFORMATIVE_ATTRS = ("title", "alt", "aria-label", "datetime", "data-value", "data-date", "href")

    def extract_from_markup(self, *, url: str, markup: str, max_chars: int = 12000) -> BrowserFetchResult:
        if not isinstance(markup, str) or not markup.strip():
            return BrowserFetchResult(url=url, status="empty_document")
        attribute_text = self._extract_attribute_text(markup)
        visible_text = self._extract_visible_text(markup)
        return BrowserFetchResult(
            url=url,
            status="success",
            visible_text=visible_text[:max_chars],
            markup_excerpt=markup[:max_chars],
            attribute_text=attribute_text[:max_chars],
            metadata={"extraction_mode": "static_or_rendered_markup"},
        )

    def _extract_visible_text(self, markup: str) -> str:
        stripped = re.sub(r"<script[\s\S]*?</script>", " ", markup, flags=re.I)
        stripped = re.sub(r"<style[\s\S]*?</style>", " ", stripped, flags=re.I)
        stripped = re.sub(r"<[^>]+>", " ", stripped)
        stripped = html.unescape(stripped)
        return re.sub(r"\s+", " ", stripped).strip()

    def _extract_attribute_text(self, markup: str) -> str:
        parts: list[str] = []
        for attr in self.INFORMATIVE_ATTRS:
            pattern = rf"\b{re.escape(attr)}\s*=\s*(['\"])(.*?)\1"
            for match in re.finditer(pattern, markup, flags=re.I | re.S):
                value = html.unescape(match.group(2)).strip()
                if value and len(value) < 500:
                    parts.append(value)
        return "\n".join(dict.fromkeys(parts))
