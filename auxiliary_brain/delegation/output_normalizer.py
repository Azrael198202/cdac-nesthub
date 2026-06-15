from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any
import json
import re


class OutputNormalizer:
    """Convert arbitrary public runtime output into safe text/html material.

    The normalizer is intentionally capability-neutral.  It does not know any
    domain vocabulary; it only recognizes generic JSON shapes, URLs, local file
    paths, and common media URL/file extensions so downstream renderers and
    side-effect tools can receive stable scalar fields.
    """

    _URL_RE = re.compile(r"https?://[^\s<>()\"']+", re.IGNORECASE)
    _IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"}
    _VIDEO_EXT = {".mp4", ".webm", ".mov", ".m4v", ".avi"}
    _PUBLIC_KEYS = (
        "title", "name", "summary", "description", "content", "text", "message",
        "source", "url", "link", "href", "image", "image_url", "thumbnail",
        "published_at", "publishedAt", "time", "date", "author",
    )

    def normalize(self, value: Any) -> dict[str, Any]:
        safe = self._json_safe(value)
        text = self.to_text(safe)
        html = self.to_html(safe)
        media = self.collect_media(safe)
        return {
            "value": safe,
            "text": text,
            "html": html,
            "media": media,
            "attachments": self.collect_local_paths(safe),
        }

    def to_text(self, value: Any) -> str:
        value = self._json_safe(value)
        if value in (None, "", [], {}):
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (int, float, bool)):
            return str(value)
        if isinstance(value, list):
            parts = []
            for index, item in enumerate(value, start=1):
                text = self.to_text(item)
                if text:
                    prefix = f"{index}. " if self._list_is_structured(value) else ""
                    parts.append(prefix + text)
            return "\n\n".join(parts).strip()
        if isinstance(value, dict):
            lines: list[str] = []
            consumed: set[str] = set()
            for key in self._PUBLIC_KEYS:
                if key in value and value.get(key) not in (None, "", [], {}):
                    label = self._label(key)
                    scalar = self.to_text(value.get(key))
                    if scalar:
                        lines.append(f"{label}: {scalar}")
                        consumed.add(key)
            if lines:
                # Include additional scalar fields without exposing deep raw JSON.
                for key, item in value.items():
                    if key in consumed or item in (None, "", [], {}):
                        continue
                    if isinstance(item, (str, int, float, bool)):
                        lines.append(f"{self._label(key)}: {self.to_text(item)}")
                return "\n".join(lines).strip()
            public_children = []
            for item in value.values():
                text = self.to_text(item)
                if text:
                    public_children.append(text)
            if public_children:
                return "\n".join(public_children).strip()
            return json.dumps(value, ensure_ascii=False, indent=2)
        return str(value)

    def to_html(self, value: Any) -> str:
        value = self._json_safe(value)
        if value in (None, "", [], {}):
            return ""
        if isinstance(value, str):
            return self._text_to_html(value)
        if isinstance(value, (int, float, bool)):
            return escape(str(value))
        if isinstance(value, list):
            items = [self.to_html(item) for item in value if item not in (None, "", [], {})]
            items = [x for x in items if x]
            if not items:
                return ""
            if self._list_is_structured(value):
                return "\n".join(f'<div class="runtime-output-item">{item}</div>' for item in items)
            return "<br>\n".join(items)
        if isinstance(value, dict):
            rows: list[str] = []
            title = self._first(value, ("title", "name"))
            if title:
                rows.append(f"<h3>{escape(str(title))}</h3>")
            summary = self._first(value, ("summary", "description", "content", "text", "message"))
            if summary:
                rows.append(f"<p>{self._text_to_html(str(summary))}</p>")
            image = self._first(value, ("image", "image_url", "thumbnail"))
            if isinstance(image, str) and self._is_image_ref(image):
                src = escape(image.strip(), quote=True)
                rows.append(f'<p><img src="{src}" alt="" style="max-width:640px;height:auto;border-radius:8px;"></p>')
            link = self._first(value, ("url", "link", "href", "source"))
            if isinstance(link, str) and self._looks_like_url(link):
                href = escape(link.strip(), quote=True)
                rows.append(f'<p><a href="{href}">{href}</a></p>')
            extras = []
            used = {"title", "name", "summary", "description", "content", "text", "message", "image", "image_url", "thumbnail", "url", "link", "href", "source"}
            for key, item in value.items():
                if key in used or item in (None, "", [], {}):
                    continue
                if isinstance(item, (str, int, float, bool)):
                    extras.append(f"<strong>{escape(self._label(key))}:</strong> {self._text_to_html(str(item))}")
            if extras:
                rows.append("<p>" + "<br>".join(extras) + "</p>")
            if rows:
                return "\n".join(rows)
            return "<pre>" + escape(json.dumps(value, ensure_ascii=False, indent=2)) + "</pre>"
        return escape(str(value))

    def collect_media(self, value: Any) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        self._collect_media(self._json_safe(value), out)
        seen: set[tuple[str, str]] = set()
        unique: list[dict[str, str]] = []
        for item in out:
            key = (item.get("type", ""), item.get("url", item.get("path", "")))
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return unique

    def collect_local_paths(self, value: Any) -> list[str]:
        paths: list[str] = []
        self._collect_paths(self._json_safe(value), paths)
        seen = set()
        out = []
        for path in paths:
            if path not in seen:
                seen.add(path)
                out.append(path)
        return out

    def _collect_media(self, value: Any, out: list[dict[str, str]]) -> None:
        if isinstance(value, dict):
            for item in value.values():
                self._collect_media(item, out)
        elif isinstance(value, list):
            for item in value:
                self._collect_media(item, out)
        elif isinstance(value, str):
            for url in self._URL_RE.findall(value):
                clean = url.rstrip(".,;)]")
                if self._is_image_ref(clean):
                    out.append({"type": "image", "url": clean})
                elif self._is_video_ref(clean):
                    out.append({"type": "video", "url": clean})
                else:
                    out.append({"type": "link", "url": clean})

    def _collect_paths(self, value: Any, out: list[str]) -> None:
        if isinstance(value, dict):
            for item in value.values():
                self._collect_paths(item, out)
        elif isinstance(value, list):
            for item in value:
                self._collect_paths(item, out)
        elif isinstance(value, str):
            text = value.strip()
            if text and not self._looks_like_url(text):
                try:
                    p = Path(text).expanduser()
                    if p.exists() and p.is_file():
                        out.append(str(p))
                except Exception:
                    pass

    def _text_to_html(self, text: str) -> str:
        escaped = escape(text or "")
        def repl(match: re.Match[str]) -> str:
            url = match.group(0).rstrip(".,;)]")
            suffix = match.group(0)[len(url):]
            href = escape(url, quote=True)
            if self._is_image_ref(url):
                return f'<img src="{href}" alt="" style="max-width:640px;height:auto;border-radius:8px;">{escape(suffix)}'
            return f'<a href="{href}">{href}</a>{escape(suffix)}'
        # Apply URL replacement to escaped text using raw pattern over escaped-safe URL characters.
        return re.sub(r"https?://[^\s<>()\"']+", repl, escaped).replace("\n", "<br>\n")

    def _json_safe(self, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, dict):
            return {str(k): self._json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._json_safe(v) for v in value]
        try:
            json.dumps(value)
            return value
        except Exception:
            return str(value)

    def _label(self, key: Any) -> str:
        text = str(key or "").replace("_", " ").strip()
        return text[:1].upper() + text[1:] if text else "Value"

    def _first(self, data: dict[str, Any], keys: tuple[str, ...]) -> Any:
        for key in keys:
            value = data.get(key)
            if value not in (None, "", [], {}):
                return value
        return None

    def _list_is_structured(self, value: list[Any]) -> bool:
        return any(isinstance(item, dict) for item in value)

    def _looks_like_url(self, value: str) -> bool:
        return bool(re.match(r"^https?://", str(value or "").strip(), re.IGNORECASE))

    def _is_image_ref(self, value: str) -> bool:
        clean = str(value or "").split("?", 1)[0].split("#", 1)[0].lower()
        return any(clean.endswith(ext) for ext in self._IMAGE_EXT)

    def _is_video_ref(self, value: str) -> bool:
        clean = str(value or "").split("?", 1)[0].split("#", 1)[0].lower()
        return any(clean.endswith(ext) for ext in self._VIDEO_EXT)
