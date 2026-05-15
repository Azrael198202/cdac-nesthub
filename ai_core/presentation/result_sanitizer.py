from __future__ import annotations

import html
import json
import re
from html.parser import HTMLParser
from typing import Any


class _GenericMarkupParser(HTMLParser):
    """Small, dependency-free extractor for visible text and repeated rows."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.visible_parts: list[str] = []
        self.current_row: list[str] | None = None
        self.rows: list[list[str]] = []
        self._skip_depth = 0
        self._current_anchor_attrs: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr_map = {str(k).lower(): str(v) for k, v in attrs if v is not None}
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
            return
        for key in ("title", "alt", "aria-label", "datetime"):
            value = attr_map.get(key)
            if value:
                self._add_text(value)
        for key, value in attr_map.items():
            if key.startswith("data-") and value and len(value) <= 80:
                self._add_text(value)
        if tag == "tr":
            self.current_row = []
        if tag == "a":
            self._current_anchor_attrs = attr_map

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag == "tr" and self.current_row is not None:
            compact = [self._compact_text(x) for x in self.current_row if self._compact_text(x)]
            if len(compact) >= 2:
                self.rows.append(compact[:8])
            self.current_row = None
        if tag == "a":
            self._current_anchor_attrs = {}

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = self._compact_text(data)
        if not text:
            return
        self._add_text(text)
        if self.current_row is not None:
            self.current_row.append(text)

    def _add_text(self, value: str) -> None:
        text = self._compact_text(value)
        if text:
            self.visible_parts.append(text)
            if self.current_row is not None:
                self.current_row.append(text)

    def _compact_text(self, value: str) -> str:
        return " ".join(html.unescape(str(value)).split())


class ResultSanitizer:
    """Removes raw transport/source payloads and keeps compact evidence material."""

    RAW_KEYS = {
        "raw",
        "raw_html",
        "html",
        "html_excerpt",
        "source_html",
        "page_html",
        "document_html",
        "debug",
        "trace",
    }
    TEXT_LIMIT = 1800
    ROW_LIMIT = 8

    def sanitize_materials(self, materials: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self.sanitize_material(item) for item in materials if isinstance(item, dict)]

    def sanitize_material(self, material: dict[str, Any]) -> dict[str, Any]:
        clone = dict(material)
        clone["content"] = self.sanitize_value(clone.get("content"))
        return clone

    def sanitize_value(self, value: Any) -> Any:
        if isinstance(value, dict):
            return self._sanitize_dict(value)
        if isinstance(value, list):
            return [self.sanitize_value(v) for v in value[:20]]
        if isinstance(value, str):
            return self._sanitize_text(value)
        return value

    def _sanitize_dict(self, value: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        markup_sources: list[str] = []
        for key, item in value.items():
            key_text = str(key)
            if key_text in self.RAW_KEYS:
                if isinstance(item, str):
                    markup_sources.append(item)
                continue
            if isinstance(item, str) and self._looks_like_markup(item):
                markup_sources.append(item)
                continue
            result[key_text] = self.sanitize_value(item)
        if markup_sources:
            extracted = self._extract_from_markup("\n".join(markup_sources))
            result["extracted_material"] = extracted
        return result

    def _sanitize_text(self, value: str) -> str:
        if self._looks_like_markup(value):
            extracted = self._extract_from_markup(value)
            return self._material_to_text(extracted)
        text = " ".join(value.split())
        return text[: self.TEXT_LIMIT]

    def _looks_like_markup(self, text: str) -> bool:
        sample = text[:3000].casefold()
        return "<!doctype" in sample or "<html" in sample or sample.count("<") > 35

    def _extract_from_markup(self, text: str) -> dict[str, Any]:
        parser = _GenericMarkupParser()
        try:
            parser.feed(text)
        except Exception:
            stripped = self._strip_markup(text)
            return {"text": stripped[: self.TEXT_LIMIT], "records": []}
        visible = " ".join(parser.visible_parts)
        visible = " ".join(visible.split())
        rows = self._dedupe_rows(parser.rows)
        return {
            "text": visible[: self.TEXT_LIMIT],
            "records": rows[: self.ROW_LIMIT],
            "raw_omitted": True,
        }

    def _dedupe_rows(self, rows: list[list[str]]) -> list[list[str]]:
        seen: set[str] = set()
        result: list[list[str]] = []
        for row in rows:
            key = json.dumps(row, ensure_ascii=False)
            if key in seen:
                continue
            seen.add(key)
            result.append(row)
        return result

    def _strip_markup(self, text: str) -> str:
        text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
        text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        return " ".join(html.unescape(text).split())

    def _material_to_text(self, material: dict[str, Any]) -> str:
        parts: list[str] = []
        text = material.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
        records = material.get("records")
        if isinstance(records, list):
            for row in records[: self.ROW_LIMIT]:
                if isinstance(row, list):
                    parts.append(" | ".join(str(x) for x in row[:8]))
        final = "\n".join(parts).strip()
        return final[: self.TEXT_LIMIT] if final else "Structured source material was retrieved; raw markup was omitted."
