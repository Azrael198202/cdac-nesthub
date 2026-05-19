from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ai_core.runtime.temporal import DateAliasGenerator


@dataclass(frozen=True)
class TargetRecord:
    canonical: str
    aliases: tuple[str, ...]


class DateAlignedRecordExtractor:
    """Extract compact records aligned to runtime target dates.

    The extractor is domain-neutral and language-neutral.  ai_core generates
    only numeric date aliases.  Natural-language aliases must come from runtime
    state or generated temporal alias contracts, so multilingual behavior is
    driven by runtime configuration rather than hard-coded source code.
    """

    VALUE_WITH_UNIT = re.compile(
        r"[-+]?\d+(?:\.\d+)?\s*(?:°\s*[CFcf]?|%|mm|cm|m|km/h|mph|hPa|kPa|kg|g|ml|L|l|円|¥|\$|€)"
    )
    NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?")
    WORD = re.compile(r"[^\W\d_][^\W\d_\-]{1,32}", re.UNICODE)
    SHORT_INTEGER = re.compile(r"(?<![\d.])\d{1,2}(?![\d.])")

    def __init__(self) -> None:
        self.alias_generator = DateAliasGenerator()

    def extract(
        self,
        *,
        text: str,
        runtime_variables: dict[str, list[str]],
        source_url: str = "",
        runtime_state: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        compact = " ".join(str(text or "").split())
        if not compact:
            return []
        targets = self._targets(runtime_variables, runtime_state or {})
        if not targets:
            return []
        facts: list[dict[str, Any]] = []
        for target in targets:
            record_text = self._find_record(compact, target)
            if not record_text:
                continue
            display = self._display_record(record_text, target)
            if not display:
                continue
            facts.append({
                "kind": "aligned_record",
                "label": "target_record",
                "value": display,
                "unit": "",
                "context": record_text,
                "confidence": 0.92,
                "source_url": source_url,
                "target": target.canonical,
            })
        return self._dedupe(facts)

    def _targets(self, runtime_variables: dict[str, list[str]], runtime_state: dict[str, Any]) -> list[TargetRecord]:
        targets: list[TargetRecord] = []
        seen: set[str] = set()
        for aliases in runtime_variables.values():
            for raw in aliases:
                text = str(raw or "").strip()
                match = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$", text)
                if not match:
                    continue
                year, month_s, day_s = match.groups()
                month = int(month_s)
                day = int(day_s)
                if not (1 <= month <= 12 and 1 <= day <= 31):
                    continue
                canonical = f"{int(year):04d}-{month:02d}-{day:02d}"
                if canonical in seen:
                    continue
                seen.add(canonical)
                alias_candidates = self.alias_generator.aliases_for(canonical, runtime_state=runtime_state)
                targets.append(TargetRecord(canonical=canonical, aliases=tuple(alias_candidates)))
        return targets

    def _find_record(self, text: str, target: TargetRecord) -> str:
        # Prefer aliases with separators/full values. Day-only aliases are weak
        # and are accepted only when the following text looks like a compact row.
        strong_aliases = [a for a in target.aliases if not re.fullmatch(r"\d{1,2}", a)]
        weak_aliases = [a for a in target.aliases if re.fullmatch(r"\d{1,2}", a)]
        for aliases in (strong_aliases, weak_aliases):
            for alias in aliases:
                found = self._record_after_alias(text, alias, weak=alias in weak_aliases)
                if found:
                    return found
        return ""

    def _record_after_alias(self, text: str, alias: str, *, weak: bool) -> str:
        pattern = re.compile(r"(?<![\w.])" + re.escape(alias) + r"(?![\w.])", re.IGNORECASE | re.UNICODE)
        for match in pattern.finditer(text):
            start = match.start()
            sample = text[start:min(len(text), start + 220)]
            if weak and (self._looks_like_embedded_measure(sample, alias) or not self._looks_like_record_start(sample)):
                continue
            sample = self._cut_at_next_record(sample)
            if self._record_quality(sample, weak=weak):
                return sample.strip(" ;,|-")
        return ""

    def _cut_at_next_record(self, sample: str) -> str:
        # Generic next-row detector. It looks for a short leading row key
        # followed by descriptor-like text and measurements, without knowing
        # any language-specific month names or business terms.
        best = len(sample)
        for match in self.SHORT_INTEGER.finditer(sample):
            if match.start() <= 0:
                continue
            tail = sample[match.start(): min(len(sample), match.start() + 90)]
            token = match.group(0)
            if not self._looks_like_embedded_measure(tail, token) and self._looks_like_record_start(tail):
                best = min(best, match.start())
        return sample[:best]

    def _looks_like_embedded_measure(self, text: str, alias: str) -> bool:
        sample = str(text or "")
        after = sample[len(str(alias or "")):].lstrip()
        return bool(after.startswith(("°", "%", "/", ".")) or re.match(r"^(?:mm|cm|m|km/h|mph|hPa|kPa)\b", after, flags=re.IGNORECASE))

    def _looks_like_record_start(self, text: str) -> bool:
        sample = str(text or "")[:90]
        if not re.match(r"^\d{1,2}\b", sample):
            return False
        has_measure = bool(self.VALUE_WITH_UNIT.search(sample))
        words = [w for w in self.WORD.findall(sample) if w.casefold() not in {"mm", "cm", "km", "mph", "hpa", "kpa"}]
        numbers = self.NUMBER.findall(sample)
        return (has_measure and len(words) >= 1) or (len(words) >= 1 and len(numbers) >= 3)

    def _record_quality(self, sample: str, *, weak: bool) -> bool:
        unit_count = len(self.VALUE_WITH_UNIT.findall(sample))
        words = self.WORD.findall(sample)
        numbers = self.NUMBER.findall(sample)
        if unit_count >= 2:
            return True
        if unit_count >= 1 and len(words) >= 1:
            return True
        return bool(not weak and len(numbers) >= 3 and len(words) >= 1)

    def _display_record(self, record_text: str, target: TargetRecord) -> str:
        text = " ".join(str(record_text or "").split())
        if not text:
            return ""
        prefix = self._best_alias_prefix(text, target)
        body = text[len(prefix):].strip(" :;-|,") if prefix else text
        body = self._cut_noise_tail(body)
        if len(body) > 180:
            body = body[:180].rsplit(" ", 1)[0].strip()
        if not body:
            return prefix or target.canonical
        return f"{prefix or target.canonical}: {body}"

    def _cut_noise_tail(self, text: str) -> str:
        # Only generic website boilerplate markers. No domain vocabulary.
        return re.split(r"\b(?:Copyright|Privacy|Terms|Contact|Feedback)\b", text, flags=re.IGNORECASE)[0].strip()

    def _best_alias_prefix(self, text: str, target: TargetRecord) -> str:
        for alias in target.aliases:
            if text.casefold().startswith(alias.casefold()):
                return text[:len(alias)]
        return target.canonical

    def _dedupe(self, facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for fact in facts:
            key = str(fact.get("target")) + "|" + str(fact.get("value"))[:100]
            if key in seen:
                continue
            seen.add(key)
            result.append(fact)
        return result
