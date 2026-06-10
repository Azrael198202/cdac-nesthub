from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


class LinkRenderer:
    """Render URLs in final presentation text as clickable Markdown links.

    This belongs to presentation_brain because it changes only expression and
    delivery. It does not change facts, execute tools, or choose sources.
    """

    URL_RE = re.compile(r"(?<!\]\()(?P<url>https?://[^\s<>)\]]+)", re.IGNORECASE)

    def render(self, text: str, *, source_titles: dict[str, str] | None = None) -> str:
        source_titles = source_titles or {}
        raw = str(text or "")
        if not raw:
            return raw
        lines = raw.splitlines()
        rendered = [self._render_line(line, source_titles=source_titles) for line in lines]
        return "\n".join(rendered)

    def _render_line(self, line: str, *, source_titles: dict[str, str]) -> str:
        if "```" in line:
            return line
        def repl(match: re.Match[str]) -> str:
            url = match.group("url").rstrip(".,;，。")
            suffix = match.group("url")[len(url):]
            label = source_titles.get(url) or self._label_from_url(url)
            return f"[{label}]({url})" + suffix
        return self.URL_RE.sub(repl, line)

    def source_titles_from_materials(self, materials: list[dict[str, Any]] | None) -> dict[str, str]:
        titles: dict[str, str] = {}
        def visit(value: Any) -> None:
            if isinstance(value, dict):
                url = ""
                for key in ("url", "source_url", "evidence_url", "href"):
                    candidate = value.get(key)
                    if isinstance(candidate, str) and candidate.startswith(("http://", "https://")):
                        url = candidate.strip()
                        break
                title = str(value.get("title") or value.get("name") or value.get("source_title") or "").strip()
                if url and title and url not in titles:
                    titles[url] = self._clean_label(title)
                for child in value.values():
                    if isinstance(child, (dict, list)):
                        visit(child)
            elif isinstance(value, list):
                for item in value[:200]:
                    visit(item)
        visit(materials or [])
        return titles

    def _label_from_url(self, url: str) -> str:
        try:
            parsed = urlparse(url)
            host = parsed.netloc.replace("www.", "")
            path = parsed.path.strip("/").split("/")[-1].replace("-", " ").replace("_", " ")
            label = path if path and len(path) >= 4 else host
            return self._clean_label(label) or url
        except Exception:
            return url

    def _clean_label(self, value: str) -> str:
        clean = re.sub(r"\s+", " ", str(value or "")).strip()
        if len(clean) > 80:
            clean = clean[:77].rstrip() + "..."
        return clean
