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

    This component is intentionally domain-neutral. It does not know field
    names, locations, source names, month names, or business vocabulary. It
    aligns source text to runtime date aliases, rejects calendar/menu fragments,
    and keeps only compact rows that contain measurement-like signal.

    Natural-language aliases are not hard-coded here. They can be supplied by
    runtime state or generated alias contracts. The small amount of text logic in
    this file is structural: row anchors, measurement units, separators, and
    generic Unicode word boundaries.
    """

    VALUE_WITH_UNIT = re.compile(
        r"[-+]?\d+(?:\.\d+)?\s*(?:°\s*[CFcf]?|%|mm|cm|m|km/h|mph|hPa|kPa|kg|g|ml|L|l|円|¥|\$|€)"
    )
    NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?")
    WORD = re.compile(r"[^\W\d_][^\W\d_\-]{1,32}", re.UNICODE)
    # Day-number row keys only. Do not match the day part inside 5/20 or 5-20.
    SHORT_INTEGER = re.compile(r"(?<![\d./-])\d{1,2}(?![\d./-])")
    COMPACT_NUMERIC_DATE = re.compile(r"(?<![\d])\d{1,2}[/.\-]\d{1,2}(?![\d])")
    NUMBER_WORD_DATE = re.compile(r"(?<![\d])\d{1,2}(?:[^\W\d_]{0,4})?\s+[^\W\d_]{2,18}(?![^\W\d_])", re.UNICODE)

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
        all_aliases = [alias for target in targets for alias in target.aliases]
        for target in targets:
            candidates = self._find_records(compact, target, all_aliases=all_aliases)
            for record_text, score in candidates[:2]:
                display = self._display_record(record_text, target)
                if not display:
                    continue
                facts.append({
                    "kind": "aligned_record",
                    "label": "target_record",
                    "value": display,
                    "unit": "",
                    "context": record_text,
                    "confidence": min(0.99, max(0.5, score)),
                    "source_url": source_url,
                    "target": target.canonical,
                })
        return self._dedupe_best(facts)

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

    def _find_records(self, text: str, target: TargetRecord, *, all_aliases: list[str]) -> list[tuple[str, float]]:
        # Prefer complete and separator-bearing aliases. Day-only aliases are weak
        # and must pass stricter row checks.
        strong_aliases = [a for a in target.aliases if not re.fullmatch(r"\d{1,2}", a)]
        weak_aliases = [a for a in target.aliases if re.fullmatch(r"\d{1,2}", a)]
        candidates: list[tuple[str, float]] = []
        for aliases, weak in ((strong_aliases, False), (weak_aliases, True)):
            for alias in aliases:
                candidates.extend(self._records_after_alias(text, alias, weak=weak, all_aliases=all_aliases))
        candidates.sort(key=lambda item: item[1], reverse=True)
        return self._dedupe_candidates(candidates)

    def _alias_pattern(self, alias: str, *, weak: bool) -> re.Pattern[str]:
        escaped = re.escape(alias)
        if weak:
            # Generic ordinal-like suffix support: it accepts a few following
            # letters without encoding any language-specific month/day words.
            return re.compile(r"(?<![\d.])" + escaped + r"(?:[^\W\d_]{0,4})?(?![\d.])", re.IGNORECASE | re.UNICODE)
        return re.compile(r"(?<![\w.])" + escaped + r"(?![\w.])", re.IGNORECASE | re.UNICODE)

    def _records_after_alias(self, text: str, alias: str, *, weak: bool, all_aliases: list[str]) -> list[tuple[str, float]]:
        pattern = self._alias_pattern(alias, weak=weak)
        candidates: list[tuple[str, float]] = []
        for match in pattern.finditer(text):
            start = match.start()
            sample = text[start:min(len(text), start + 520)]
            if weak and self._looks_like_embedded_measure(sample, alias):
                continue
            if self._looks_like_calendar_or_menu_fragment(sample):
                continue
            sample = self._cut_at_next_record(sample, current_alias=alias, all_aliases=all_aliases)
            quality = self._record_quality_score(sample, weak=weak)
            if quality >= (0.70 if weak else 0.62):
                candidates.append((sample.strip(" ;,|-"), quality))
        return candidates

    def _cut_at_next_record(self, sample: str, *, current_alias: str, all_aliases: list[str]) -> str:
        best = len(sample)
        # Cut at another explicit alias, but never at the current leading alias.
        for alias in sorted(set(all_aliases), key=len, reverse=True):
            if not alias or alias.casefold() == current_alias.casefold():
                continue
            if len(alias) < 2:
                continue
            try:
                pat = self._alias_pattern(alias, weak=bool(re.fullmatch(r"\d{1,2}", alias)))
            except Exception:
                continue
            for match in pat.finditer(sample):
                if match.start() <= 8:
                    continue
                prefix = sample[:match.start()]
                # Do not cut before the first real measurement, otherwise a
                # calendar strip such as "19 20 21" becomes a false row.
                if self.VALUE_WITH_UNIT.search(prefix):
                    best = min(best, match.start())
        # Cut at compact numeric date anchors such as N/N or N-N when they
        # appear after the current row has already produced a measurement.
        for pattern in (self.COMPACT_NUMERIC_DATE, self.NUMBER_WORD_DATE):
            for match in pattern.finditer(sample):
                if match.start() <= 8:
                    continue
                prefix = sample[:match.start()]
                if self.VALUE_WITH_UNIT.search(prefix):
                    best = min(best, self._trim_before_separator_word(sample, match.start()))

        # Generic next-row detector for rendered table text.
        for match in self.SHORT_INTEGER.finditer(sample):
            if match.start() <= 8:
                continue
            tail = sample[match.start(): min(len(sample), match.start() + 110)]
            token = match.group(0)
            if not self._looks_like_embedded_measure(tail, token) and self._looks_like_record_start(tail):
                prefix = sample[:match.start()]
                if self.VALUE_WITH_UNIT.search(prefix):
                    best = min(best, self._trim_before_separator_word(sample, match.start()))
        return sample[:best]

    def _trim_before_separator_word(self, sample: str, cut_index: int) -> int:
        prefix = sample[:cut_index].rstrip()
        # If a compact next-date anchor is preceded by one isolated connector
        # word, trim that connector as part of the next row. This is structural
        # cleanup and does not encode any particular language vocabulary.
        match = re.search(r"\s+[^\W\d_]{1,12}\s*$", prefix, flags=re.UNICODE)
        if not match:
            return cut_index
        before = prefix[:match.start()]
        if self.VALUE_WITH_UNIT.search(before):
            return match.start()
        return cut_index

    def _looks_like_calendar_or_menu_fragment(self, sample: str) -> bool:
        head = str(sample or "")[:150]
        first_measure = self.VALUE_WITH_UNIT.search(head)
        before_measure = head[: first_measure.start()] if first_measure else head
        short_numbers = re.findall(r"(?<![\d.])\d{1,2}(?![\d.])", before_measure)
        compact_dates = self.COMPACT_NUMERIC_DATE.findall(before_measure)
        number_word_dates = self.NUMBER_WORD_DATE.findall(before_measure)
        # Many date anchors before any measurement usually indicate a navigation
        # strip or date selector, not a data row.
        if len(short_numbers) >= 4 or len(compact_dates) >= 3 or len(number_word_dates) >= 3:
            return True
        # A pure date-label chain with no measurement in the first segment is
        # also not usable evidence.
        if not first_measure and (len(short_numbers) >= 2 or len(compact_dates) >= 2 or len(number_word_dates) >= 2):
            return True
        return False

    def _looks_like_embedded_measure(self, text: str, alias: str) -> bool:
        sample = str(text or "")
        after = sample[len(str(alias or "")):].lstrip()
        return bool(after.startswith(("°", "%", "/", ".")) or re.match(r"^(?:mm|cm|m|km/h|mph|hPa|kPa)\b", after, flags=re.IGNORECASE))

    def _looks_like_record_start(self, text: str) -> bool:
        sample = str(text or "")[:120]
        if not re.match(r"^\d{1,2}(?:[^\W\d_]{0,4})?\b", sample, flags=re.UNICODE):
            return False
        has_measure = bool(self.VALUE_WITH_UNIT.search(sample))
        words = [w for w in self.WORD.findall(sample) if w.casefold() not in {"mm", "cm", "km", "mph", "hpa", "kpa"}]
        numbers = self.NUMBER.findall(sample)
        return (has_measure and len(words) >= 1) or (len(words) >= 1 and len(numbers) >= 3)

    def _record_quality_score(self, sample: str, *, weak: bool) -> float:
        text = " ".join(str(sample or "").split())
        if not text:
            return 0.0
        if self._looks_like_calendar_or_menu_fragment(text):
            return 0.0
        unit_count = len(self.VALUE_WITH_UNIT.findall(text))
        numbers = self.NUMBER.findall(text)
        words = self.WORD.findall(text)
        score = 0.38
        score += min(unit_count, 6) * 0.095
        score += min(len(numbers), 8) * 0.025
        score += min(len(words), 8) * 0.015
        if weak:
            score -= 0.12
        if self.NUMBER_WORD_DATE.match(text) and not self.COMPACT_NUMERIC_DATE.match(text):
            score -= 0.26
        if len(text) > 260:
            score -= 0.08
        if len(text) > 420:
            score -= 0.16
        # Penalize record-like text that has many anchors before the first unit.
        first_measure = self.VALUE_WITH_UNIT.search(text)
        if first_measure:
            before = text[:first_measure.start()]
            if len(re.findall(r"(?<![\d.])\d{1,2}(?![\d.])", before)) >= 3:
                score -= 0.22
        return max(0.0, min(0.99, score))

    def _display_record(self, record_text: str, target: TargetRecord) -> str:
        text = " ".join(str(record_text or "").split())
        if not text:
            return ""
        prefix = self._best_alias_prefix(text, target)
        body = text[len(prefix):].strip(" :;-|,") if prefix else text
        body = self._cut_noise_tail(body)
        body = self._cut_at_embedded_later_anchor(body)
        if len(body) > 220:
            body = body[:220].rsplit(" ", 1)[0].strip()
        if not body:
            return prefix or target.canonical
        return f"{prefix or target.canonical}: {body}"

    def _cut_at_embedded_later_anchor(self, text: str) -> str:
        sample = str(text or "")
        patterns = [self.COMPACT_NUMERIC_DATE, self.NUMBER_WORD_DATE]
        best = len(sample)
        for pattern in patterns:
            for match in pattern.finditer(sample):
                if match.start() < 24:
                    continue
                prefix = sample[:match.start()]
                if self.VALUE_WITH_UNIT.search(prefix):
                    best = min(best, match.start())
        return sample[:best].strip(" ;,|-")

    def _cut_noise_tail(self, text: str) -> str:
        # Only generic website boilerplate markers. No domain vocabulary.
        return re.split(r"\b(?:Copyright|Privacy|Terms|Contact|Feedback)\b", text, flags=re.IGNORECASE)[0].strip()

    def _best_alias_prefix(self, text: str, target: TargetRecord) -> str:
        for alias in sorted(target.aliases, key=len, reverse=True):
            pat = self._alias_pattern(alias, weak=bool(re.fullmatch(r"\d{1,2}", alias)))
            match = pat.match(text)
            if match:
                return text[:match.end()]
        return target.canonical

    def _dedupe_candidates(self, candidates: list[tuple[str, float]]) -> list[tuple[str, float]]:
        result: list[tuple[str, float]] = []
        seen: set[str] = set()
        for text, score in candidates:
            key = re.sub(r"\s+", " ", text.casefold())[:140]
            if key in seen:
                continue
            seen.add(key)
            result.append((text, score))
        return result

    def _dedupe_best(self, facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        best_by_target: dict[str, dict[str, Any]] = {}
        for fact in facts:
            target = str(fact.get("target") or "")
            if not target:
                continue
            existing = best_by_target.get(target)
            if existing is None or float(fact.get("confidence") or 0) > float(existing.get("confidence") or 0):
                best_by_target[target] = fact
        return list(best_by_target.values())
