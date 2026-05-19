from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any

from ai_core.runtime.semantic import RuntimeSemanticContractEngine
from ai_core.presentation.date_aligned_record_extractor import DateAlignedRecordExtractor
from ai_core.runtime.temporal import DateAliasGenerator


_DEBUG_MARKERS = (
    "Matched Parameter:",
    "Descriptors:",
    "Values:",
    "matched parameter",
    "descriptors",
    "values",
)


@dataclass
class NormalizedFact:
    kind: str
    label: str
    value: str
    unit: str = ""
    context: str = ""
    confidence: float = 0.6
    source_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class StructuredFactNormalizer:
    """Converts intermediate extraction artifacts into normalized facts.

    The class is intentionally domain-neutral. It does not know any business or
    professional vocabulary. It uses only runtime parameters, generic numeric
    patterns, units, records, and source references.
    """

    VALUE_PATTERN = re.compile(
        r"(?P<value>[-+]?\d+(?:\.\d+)?)\s*(?P<unit>°\s*[CFcf]?|%|mm|cm|m|km/h|mph|hPa|kPa|kg|g|ml|L|l|円|¥|\$|€)?"
    )

    def __init__(self) -> None:
        self.date_aligned_extractor = DateAlignedRecordExtractor()
        self.date_alias_generator = DateAliasGenerator()

    def normalize(self, *, materials: list[dict[str, Any]], state: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        runtime_variables = self._runtime_variables(state or {})
        facts: list[NormalizedFact] = []
        for material in materials:
            if not isinstance(material, dict):
                continue
            source_url = self._source_url(material)
            content = material.get("content")
            facts.extend(self._facts_from_value(content, runtime_variables=runtime_variables, source_url=source_url))
        deduped = self._dedupe([f.to_dict() for f in facts])
        return RuntimeSemanticContractEngine().verify_facts(deduped, state=state or {})

    def reject_debug_text(self, text: str) -> bool:
        sample = str(text or "")[:4000]
        return any(marker in sample for marker in _DEBUG_MARKERS)

    def _facts_from_value(self, value: Any, *, runtime_variables: dict[str, list[str]], source_url: str) -> list[NormalizedFact]:
        if isinstance(value, dict):
            return self._facts_from_dict(value, runtime_variables=runtime_variables, source_url=source_url)
        if isinstance(value, list):
            facts: list[NormalizedFact] = []
            for item in value[:20]:
                facts.extend(self._facts_from_value(item, runtime_variables=runtime_variables, source_url=source_url))
            return facts
        if isinstance(value, str):
            return self._facts_from_text(value, runtime_variables=runtime_variables, source_url=source_url)
        return []

    def _facts_from_dict(self, value: dict[str, Any], *, runtime_variables: dict[str, list[str]], source_url: str) -> list[NormalizedFact]:
        facts: list[NormalizedFact] = []
        if isinstance(value.get("normalized_facts"), list):
            for item in value["normalized_facts"][:20]:
                if isinstance(item, dict):
                    fact = self._coerce_fact(item, source_url=source_url)
                    if fact:
                        facts.append(fact)
            return facts

        if isinstance(value.get("source_documents"), list):
            for doc in value.get("source_documents")[:6]:
                if isinstance(doc, dict):
                    doc_url = str(doc.get("source_url") or source_url or "")
                    text = doc.get("text")
                    if isinstance(text, str):
                        facts.extend(self._facts_from_text(text, runtime_variables=runtime_variables, source_url=doc_url))

        extracted = value.get("extracted_material") if isinstance(value.get("extracted_material"), dict) else value
        records = extracted.get("records") if isinstance(extracted, dict) else None
        if isinstance(records, list):
            for row in records[:30]:
                if isinstance(row, list):
                    text = " | ".join(str(x) for x in row)
                    facts.extend(self._facts_from_text(text, runtime_variables=runtime_variables, source_url=source_url))
        text = extracted.get("text") if isinstance(extracted, dict) else None
        if isinstance(text, str):
            facts.extend(self._facts_from_text(text, runtime_variables=runtime_variables, source_url=source_url))

        # Generic key-value extraction for already structured payloads.
        # Exclude known intermediate-carrier keys that usually contain traces
        # rather than user-facing facts.  This is not domain logic; it is a
        # runtime artifact hygiene boundary.
        for key, item in value.items():
            if key in {"raw", "html", "trace", "debug", "extracted_material", "normalized_facts", "answer_material", "attempt_summary"}:
                continue
            if isinstance(item, (str, int, float)):
                text = f"{key}: {item}"
                facts.extend(self._facts_from_text(text, runtime_variables=runtime_variables, source_url=source_url))
            elif isinstance(item, (dict, list)):
                facts.extend(self._facts_from_value(item, runtime_variables=runtime_variables, source_url=source_url))
        return facts

    def _facts_from_text(self, text: str, *, runtime_variables: dict[str, list[str]], source_url: str) -> list[NormalizedFact]:
        compact = " ".join(str(text or "").split())
        if not compact:
            return []
        # Intermediate extraction traces are useful for debugging but are not
        # user-facing evidence.  The runtime may still provide structured
        # records next to those traces; those records are handled separately.
        if self.reject_debug_text(compact):
            return []
        aligned_records = self.date_aligned_extractor.extract(
            text=compact,
            runtime_variables=runtime_variables,
            source_url=source_url,
            runtime_state=getattr(self, "_current_state", {}) if hasattr(self, "_current_state") else {},
        )
        if aligned_records:
            return [self._fact_from_aligned_record(item) for item in aligned_records]

        relevant_windows = self._relevant_windows(compact, runtime_variables)
        if not relevant_windows:
            relevant_windows = self._signal_windows(compact)
        if not relevant_windows:
            relevant_windows = [compact[:900]]
        facts: list[NormalizedFact] = []
        for window in relevant_windows[:10]:
            # Keep one concise source-backed statement for synthesis. It gives
            # the final composer enough context to write a natural answer while
            # still avoiding raw page dumps.
            if self._is_source_backed_statement(window, runtime_variables):
                facts.append(NormalizedFact(
                    kind="supporting_statement",
                    label="statement",
                    value=self._statement_from_window(window),
                    context=self._statement_from_window(window),
                    confidence=0.76,
                    source_url=source_url,
                ))
            for match in self.VALUE_PATTERN.finditer(window):
                value = match.group("value")
                unit = (match.group("unit") or "").replace(" ", "")
                if not value:
                    continue
                context = self._trim_context(window, match.start(), match.end())
                if self._looks_like_navigation_or_date_only(context=context, value=value, unit=unit):
                    continue
                label = self._label_from_context(context, value=value, unit=unit)
                facts.append(NormalizedFact(
                    kind="observed_value",
                    label=label,
                    value=value,
                    unit=unit,
                    context=context,
                    confidence=self._confidence(context, runtime_variables),
                    source_url=source_url,
                ))
        return facts


    def _fact_from_aligned_record(self, item: dict[str, Any]) -> NormalizedFact:
        return NormalizedFact(
            kind=str(item.get("kind") or "aligned_record"),
            label=str(item.get("label") or "target_record"),
            value=str(item.get("value") or ""),
            unit=str(item.get("unit") or ""),
            context=str(item.get("context") or ""),
            confidence=float(item.get("confidence") or 0.9),
            source_url=str(item.get("source_url") or ""),
        )

    def _signal_windows(self, text: str) -> list[str]:
        """Find generic windows with measurement-like signal.

        This is deliberately domain-neutral: it searches for units, ratios,
        dates, and source-style records rather than business nouns.
        """
        windows: list[str] = []
        for match in self.VALUE_PATTERN.finditer(text):
            unit = (match.group("unit") or "").strip()
            if not unit:
                continue
            start = max(0, match.start() - 260)
            end = min(len(text), match.end() + 420)
            sample = text[start:end]
            if sample not in windows:
                windows.append(sample)
            if len(windows) >= 12:
                break
        return windows

    def _is_source_backed_statement(self, window: str, runtime_variables: dict[str, list[str]]) -> bool:
        if self.reject_debug_text(window):
            return False
        has_measure = bool(re.search(r"\d+(?:\.\d+)?\s*(?:°\s*[CFcf]?|%|mm|km/h|mph|hPa|kPa)", window))
        has_runtime_anchor = self._mentions_runtime_value(window, runtime_variables)
        return has_measure and (has_runtime_anchor or len(window) < 900)

    def _statement_from_window(self, window: str) -> str:
        text = " ".join(str(window or "").split())
        # Remove leading calendar/navigation sequences before selecting the
        # source-backed statement. This is generic page-cleanup, not domain
        # reasoning.
        text = re.sub(r"^(?:\d{1,2}\s+[A-Za-z]{3,9}\s*){2,}", "", text).strip()
        # Keep the sentence-like part around the densest measurement section.
        matches = list(self.VALUE_PATTERN.finditer(text))
        if not matches:
            return text[:420]
        mid = matches[min(len(matches) // 2, len(matches) - 1)].start()
        start = max(0, mid - 220)
        end = min(len(text), mid + 360)
        sample = text[start:end].strip(" ,;|-")
        sample = re.sub(r"^(?:\d{1,2}\s+[A-Za-z]{3,9}\s*){1,}", "", sample).strip()
        return sample[:520]

    def _looks_like_navigation_or_date_only(self, *, context: str, value: str, unit: str) -> bool:
        # Generic hygiene: unit-less short integers in calendar-like or menu-like
        # contexts are usually navigation, not measurements. Unit-bearing values
        # remain eligible and are validated later by the semantic contract engine.
        if unit:
            return False
        try:
            number = float(value)
        except Exception:
            return True
        sample = str(context or "")[:240]
        tokens = re.findall(r"[A-Za-z]{3,}", sample)
        punctuation_density = sample.count("/") + sample.count("|") + sample.count("→")
        # Calendar/menu-like sequences with many short unit-less numbers are
        # not measurements.  Language-specific month names are intentionally
        # not hard-coded here.
        if number <= 31 and len(re.findall(r"(?<![\d.])\d{1,2}(?![\d.])", sample)) >= 4 and not unit:
            return True
        if len(tokens) > 18 and punctuation_density >= 2:
            return True
        # Unit-less long numeric values may still be useful ids/timestamps, but
        # they are not user-facing measurements unless explicitly structured.
        if len(str(value).split(".")[0]) >= 6:
            return True
        return False

    def _relevant_windows(self, text: str, runtime_variables: dict[str, list[str]]) -> list[str]:
        aliases = [alias for aliases in runtime_variables.values() for alias in aliases if len(alias) >= 2]
        windows: list[str] = []
        lowered = text.casefold()
        for alias in aliases:
            needle = alias.casefold()
            start = 0
            while True:
                idx = lowered.find(needle, start)
                if idx < 0:
                    break
                windows.append(text[max(0, idx - 180): idx + 360])
                start = idx + len(needle)
                if len(windows) >= 16:
                    return windows
        return windows

    def _mentions_runtime_value(self, text: str, runtime_variables: dict[str, list[str]]) -> bool:
        sample = text.casefold()
        for aliases in runtime_variables.values():
            if any(str(alias).casefold() in sample for alias in aliases if alias):
                return True
        return False

    def _confidence(self, context: str, runtime_variables: dict[str, list[str]]) -> float:
        score = 0.55
        if self._mentions_runtime_value(context, runtime_variables):
            score += 0.22
        if any(unit in context for unit in ("°", "%", "mm", "km/h", "mph")):
            score += 0.12
        return min(score, 0.95)

    def _trim_context(self, text: str, start: int, end: int) -> str:
        return " ".join(text[max(0, start - 90): min(len(text), end + 120)].split())[:260]

    def _label_from_context(self, context: str, value: str = "", unit: str = "") -> str:
        sample = str(context or "")
        value_pattern = re.escape(str(value or ""))
        unit_pattern = re.escape(str(unit or "")) if unit else r"(?:°\s*[CFcf]?|%|mm|cm|m|km/h|mph|hPa|kPa|kg|g|ml|L|l|円|¥|\$|€)?"
        # Prefer a concise label that appears immediately after a measurement;
        # many tables are rendered as "28 ° Temp 0% Ratio ...".
        if value_pattern:
            after_match = re.search(value_pattern + r"\s*" + unit_pattern + r"\s*/?\s*([A-Za-z][A-Za-z_-]{1,24}(?:\s+[A-Za-z][A-Za-z_-]{1,24}){0,2})", sample)
            if after_match:
                words = after_match.group(1).strip()
                if not re.match(r"^\d", words):
                    return words.split()[0][:48]
        before = sample.split(":", 1)[0].strip()
        if before and len(before) <= 48:
            return before
        # Generic fallback: use the closest short alphabetic phrase before the
        # value rather than a whole page fragment.
        prefix = re.sub(r"[-+]?\d+(?:\.\d+)?\s*(?:°\s*[CFcf]?|%|mm|cm|m|km/h|mph|hPa|kPa|kg|g|ml|L|l|円|¥|\$|€)?.*$", "", sample).strip()
        words = re.findall(r"[A-Za-z][A-Za-z_-]{1,24}", prefix)
        if words:
            return " ".join(words[-4:])[:48]
        return "value"

    def _runtime_variables(self, state: dict[str, Any]) -> dict[str, list[str]]:
        self._current_state = state
        return self.date_alias_generator.aliases_from_state(state)

    def _source_url(self, material: dict[str, Any]) -> str:
        for key in ("source_url", "url"):
            value = material.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return value
        content = material.get("content")
        if isinstance(content, dict):
            for key in ("source_url", "url"):
                value = content.get(key)
                if isinstance(value, str) and value.startswith(("http://", "https://")):
                    return value
        prov = material.get("provenance")
        if isinstance(prov, dict):
            value = prov.get("source_url") or prov.get("url")
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return value
        return ""

    def _coerce_fact(self, item: dict[str, Any], source_url: str) -> NormalizedFact | None:
        value = item.get("value") or item.get("text") or item.get("statement")
        if value is None:
            return None
        return NormalizedFact(
            kind=str(item.get("kind") or "observed_value"),
            label=str(item.get("label") or "value"),
            value=str(value),
            unit=str(item.get("unit") or ""),
            context=str(item.get("context") or ""),
            confidence=float(item.get("confidence") or 0.7),
            source_url=str(item.get("source_url") or source_url or ""),
        )

    def _dedupe(self, facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        result: list[dict[str, Any]] = []
        for fact in facts:
            key = "|".join(str(fact.get(k, "")) for k in ("kind", "label", "value", "unit", "source_url"))
            if key in seen:
                continue
            seen.add(key)
            result.append(fact)
            if len(result) >= 24:
                break
        return result
