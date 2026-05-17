from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


class RuntimeSemanticSurfaceNormalizer:
    """Normalize compact runtime artifacts through runtime-generated packs.

    Core does not keep domain/unit vocabularies. It only knows how to:
    - load optional runtime-generated alias packs;
    - recognize compact opaque artifacts generically;
    - map an artifact to a user-written surface span when the request contains
      the same numeric magnitude;
    - otherwise drop the artifact from semantic evidence matching.
    """

    _COMPACT_ARTIFACT_RE = re.compile(r"^[A-Z](?:\d+[A-Z])+\d*$", re.IGNORECASE)
    _NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

    def __init__(self, pack_dir: str | Path | None = None) -> None:
        self.pack_dir = Path(pack_dir or "runtime/generated/semantic_packs")
        self._packs: list[dict[str, Any]] | None = None

    def compact_parts(self, value: Any) -> dict[str, Any] | None:
        text = str(value or "").strip()
        if not text or not self._COMPACT_ARTIFACT_RE.match(text):
            return None
        numbers = self._NUMBER_RE.findall(text)
        return {"raw": text, "numbers": numbers} if numbers else None

    def is_compact_artifact(self, value: Any) -> bool:
        return self.compact_parts(value) is not None

    def surface_from_request(self, value: Any, request_text: str) -> str | None:
        compact = self.compact_parts(value)
        if not compact:
            return None
        request = str(request_text or "")
        for alias in self._aliases_from_packs(str(value), request):
            if alias:
                return alias
        for amount in compact.get("numbers", []):
            match = re.search(
                rf"(?<![A-Za-z0-9]){re.escape(amount)}\s*[-–—]?\s*[A-Za-z\u3040-\u30ff\u3400-\u9fff]{{1,12}}(?![A-Za-z0-9])",
                request,
                flags=re.IGNORECASE | re.UNICODE,
            )
            if match:
                return match.group(0).strip()
            exact = re.search(rf"(?<![A-Za-z0-9]){re.escape(amount)}(?![A-Za-z0-9])", request)
            if exact:
                return exact.group(0).strip()
        return None

    def semantic_aliases(self, value: Any, request_text: str = "") -> list[str]:
        text = str(value or "").strip()
        if not text:
            return []
        if not self.is_compact_artifact(text):
            return [text]
        aliases = self._aliases_from_packs(text, request_text)
        surface = self.surface_from_request(text, request_text)
        if surface:
            aliases.append(surface)
        return self._dedupe([x for x in aliases if x and x.casefold() != text.casefold()])

    def canonical_or_surface(self, value: Any, request_text: str = "") -> Any | None:
        if not self.is_compact_artifact(value):
            return value
        return self.surface_from_request(value, request_text)

    def generate_runtime_pack(self, *, request_text: str, values: list[Any], pack_name: str | None = None) -> dict[str, Any]:
        """Create a generic runtime alias pack from observed values and request text."""
        entries: list[dict[str, Any]] = []
        for value in values:
            raw = str(value or "").strip()
            if not self.is_compact_artifact(raw):
                continue
            surface = self.surface_from_request(raw, request_text)
            if surface:
                entries.append({"artifact": raw, "aliases": [surface], "origin": "request_surface"})
        pack = {
            "schema_version": "1.0",
            "pack_type": "runtime_semantic_surface",
            "name": pack_name or "auto_surface_pack",
            "entries": entries,
        }
        self.pack_dir.mkdir(parents=True, exist_ok=True)
        path = self.pack_dir / f"{pack['name']}.json"
        path.write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
        self._packs = None
        return pack

    def _aliases_from_packs(self, artifact: str, request_text: str) -> list[str]:
        aliases: list[str] = []
        for pack in self._load_packs():
            for entry in pack.get("entries", []) if isinstance(pack, dict) else []:
                if not isinstance(entry, dict):
                    continue
                if str(entry.get("artifact") or "").casefold() != artifact.casefold():
                    continue
                for alias in entry.get("aliases", []) or []:
                    alias_text = str(alias or "").strip()
                    if alias_text and (not request_text or alias_text.casefold() in request_text.casefold()):
                        aliases.append(alias_text)
        return aliases

    def _load_packs(self) -> list[dict[str, Any]]:
        if self._packs is not None:
            return self._packs
        packs: list[dict[str, Any]] = []
        if self.pack_dir.exists():
            for path in sorted(self.pack_dir.glob("*.json")):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        packs.append(data)
                except Exception:
                    continue
        self._packs = packs
        return packs

    def _dedupe(self, values: list[str]) -> list[str]:
        seen = set()
        out: list[str] = []
        for value in values:
            norm = value.casefold()
            if value and norm not in seen:
                out.append(value)
                seen.add(norm)
        return out
