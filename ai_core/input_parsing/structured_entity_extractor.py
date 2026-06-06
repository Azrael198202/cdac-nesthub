from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExtractedEntity:
    value: str
    start: int
    end: int
    value_type: str
    source: str = "text"

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "span": [self.start, self.end],
            "value_type": self.value_type,
            "source": self.source,
        }


class StructuredEntityExtractor:
    """Extract generic structural entities from raw user material.

    The extractor is deliberately domain-neutral.  It does not decide what a
    task means and it does not route execution.  It only preserves structural
    tokens that are easy for small models to corrupt, together with source
    spans so later stages can bind exact user-provided values instead of asking
    an LLM to reproduce them from memory.
    """

    _ELECTRONIC_ADDRESS_RE = re.compile(
        r"(?<![A-Za-z0-9.!#$%&'*+/=?^_`{|}~-])"
        r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+"
        r"@"
        r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
        r"[A-Za-z]{2,63}"
        r"(?![A-Za-z0-9.!#$%&'*+/=?^_`{|}~-])"
    )

    _URI_RE = re.compile(r"\b[a-z][a-z0-9+.-]{1,31}://[^\s<>\"']+", re.IGNORECASE)
    _DURATION_RE = re.compile(
        r"(?<![A-Za-z0-9])(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?|d)(?![A-Za-z0-9])",
        re.IGNORECASE,
    )

    def extract(self, text: str, *, source: str = "text") -> dict[str, Any]:
        text = str(text or "")
        electronic = self._dedupe(self._extract_electronic_addresses(text, source=source))
        uris = self._dedupe(self._extract_uris(text, source=source))
        durations = self._dedupe(self._extract_durations(text, source=source))
        values_by_type = {
            "electronic_address": [item.value for item in electronic],
            "uri": [item.value for item in uris],
            "duration": [item.value for item in durations],
            "duration_seconds": [self.duration_to_seconds(item.value) for item in durations if self.duration_to_seconds(item.value) is not None],
        }
        return {
            "electronic_addresses": [item.to_dict() for item in electronic],
            "uris": [item.to_dict() for item in uris],
            "durations": [item.to_dict() for item in durations],
            "values_by_type": {k: v for k, v in values_by_type.items() if v},
            # Compatibility alias for existing UI/LLM prompts that already use
            # this common structural label.  It is still a generic address
            # format, not a capability or business rule.
            "email": [item.value for item in electronic],
        }

    def first_electronic_address(self, text: str) -> str | None:
        items = self._extract_electronic_addresses(str(text or ""), source="text")
        return items[0].value if items else None

    def is_electronic_address(self, value: Any) -> bool:
        if not isinstance(value, str):
            return False
        return bool(self._ELECTRONIC_ADDRESS_RE.fullmatch(value.strip()))

    def extract_electronic_address_values(self, *values: Any) -> list[str]:
        found: list[str] = []
        seen: set[str] = set()
        for value in values:
            for text in self._flatten_text(value):
                for item in self._extract_electronic_addresses(text, source="value"):
                    key = item.value.casefold()
                    if key not in seen:
                        seen.add(key)
                        found.append(item.value)
        return found

    def _extract_electronic_addresses(self, text: str, *, source: str) -> list[ExtractedEntity]:
        return [
            ExtractedEntity(value=m.group(0), start=m.start(), end=m.end(), value_type="electronic_address", source=source)
            for m in self._ELECTRONIC_ADDRESS_RE.finditer(text or "")
        ]

    def _extract_uris(self, text: str, *, source: str) -> list[ExtractedEntity]:
        return [
            ExtractedEntity(value=m.group(0), start=m.start(), end=m.end(), value_type="uri", source=source)
            for m in self._URI_RE.finditer(text or "")
        ]

    def duration_to_seconds(self, value: Any) -> int | None:
        if isinstance(value, (int, float)):
            return int(value) if value > 0 else None
        text = str(value or "").strip()
        match = self._DURATION_RE.search(text)
        if not match:
            return None
        amount = float(match.group("num"))
        unit = match.group("unit").casefold()
        multiplier = 1
        if unit.startswith("m") and unit not in {"ms"}:
            multiplier = 60
        elif unit.startswith("h"):
            multiplier = 3600
        elif unit.startswith("d"):
            multiplier = 86400
        return max(1, int(amount * multiplier))

    def extract_duration_seconds_values(self, *values: Any) -> list[int]:
        found: list[int] = []
        seen: set[int] = set()
        for value in values:
            for text in self._flatten_text(value):
                for item in self._extract_durations(text, source="value"):
                    seconds = self.duration_to_seconds(item.value)
                    if seconds is not None and seconds not in seen:
                        seen.add(seconds)
                        found.append(seconds)
        return found

    def _extract_durations(self, text: str, *, source: str) -> list[ExtractedEntity]:
        return [
            ExtractedEntity(value=m.group(0), start=m.start(), end=m.end(), value_type="duration", source=source)
            for m in self._DURATION_RE.finditer(text or "")
        ]

    def _dedupe(self, items: list[ExtractedEntity]) -> list[ExtractedEntity]:
        out: list[ExtractedEntity] = []
        seen: set[tuple[str, str]] = set()
        for item in items:
            key = (item.value_type, item.value.casefold())
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out

    def _flatten_text(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, (int, float, bool)):
            return [str(value)]
        if isinstance(value, dict):
            out: list[str] = []
            for k, v in value.items():
                out.extend(self._flatten_text(k))
                out.extend(self._flatten_text(v))
            return out
        if isinstance(value, (list, tuple, set)):
            out: list[str] = []
            for item in value:
                out.extend(self._flatten_text(item))
            return out
        return [str(value)]
