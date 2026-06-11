from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SourceMaterialExtractor:
    """Extracts usable source material in a deterministic fallback order."""

    min_text_length: int = 120

    def extract(self, source: dict[str, Any]) -> dict[str, Any]:
        source = source if isinstance(source, dict) else {}
        for method in (self._url_page, self._visible_text, self._text_excerpt, self._search_cards):
            material = method(source)
            if material.get("status") == "available":
                return material
        return {"status": "blocked", "material_type": "blocked", "text": "", "reason": "no_usable_source_material"}

    def _url_page(self, source: dict[str, Any]) -> dict[str, Any]:
        text = self._clean(source.get("url_page_text") or source.get("page_text") or source.get("html_text"))
        if len(text) >= self.min_text_length:
            return {"status": "available", "material_type": "url_page", "text": text, "source_url": source.get("url")}
        return {"status": "missing", "material_type": "url_page"}

    def _visible_text(self, source: dict[str, Any]) -> dict[str, Any]:
        text = self._clean(source.get("visible_text") or source.get("body_text"))
        if len(text) >= self.min_text_length:
            return {"status": "available", "material_type": "visible_text", "text": text, "source_url": source.get("url")}
        return {"status": "missing", "material_type": "visible_text"}

    def _text_excerpt(self, source: dict[str, Any]) -> dict[str, Any]:
        text = self._clean(source.get("text_excerpt") or source.get("excerpt") or source.get("snippet"))
        if text:
            return {"status": "available", "material_type": "text_excerpt", "text": text, "source_url": source.get("url")}
        return {"status": "missing", "material_type": "text_excerpt"}

    def _search_cards(self, source: dict[str, Any]) -> dict[str, Any]:
        cards = source.get("search_cards") if isinstance(source.get("search_cards"), list) else []
        chunks = []
        for card in cards:
            if isinstance(card, dict):
                title = self._clean(card.get("title"))
                snippet = self._clean(card.get("snippet") or card.get("summary"))
                if title or snippet:
                    chunks.append(" - ".join([part for part in (title, snippet) if part]))
        if chunks:
            return {"status": "available", "material_type": "search_cards", "text": "\n".join(chunks), "source_url": source.get("url")}
        return {"status": "missing", "material_type": "search_cards"}

    def _clean(self, value: Any) -> str:
        return " ".join(str(value or "").split())
