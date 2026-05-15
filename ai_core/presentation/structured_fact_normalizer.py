from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any


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

    def normalize(self, *, materials: list[dict[str, Any]], state: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        runtime_variables = self._runtime_variables(state or {})
        facts: list[NormalizedFact] = []
        for material in materials:
            if not isinstance(material, dict):
                continue
            source_url = self._source_url(material)
            content = material.get("content")
            facts.extend(self._facts_from_value(content, runtime_variables=runtime_variables, source_url=source_url))
        return self._dedupe([f.to_dict() for f in facts])

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
        for key, item in value.items():
            if key in {"raw", "html", "trace", "debug", "extracted_material", "normalized_facts"}:
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
        relevant_windows = self._relevant_windows(compact, runtime_variables)
        if not relevant_windows:
            relevant_windows = [compact[:600]]
        facts: list[NormalizedFact] = []
        for window in relevant_windows[:8]:
            for match in self.VALUE_PATTERN.finditer(window):
                value = match.group("value")
                unit = (match.group("unit") or "").replace(" ", "")
                if not value:
                    continue
                context = self._trim_context(window, match.start(), match.end())
                label = self._label_from_context(context)
                facts.append(NormalizedFact(
                    kind="observed_value",
                    label=label,
                    value=value,
                    unit=unit,
                    context=context,
                    confidence=self._confidence(context, runtime_variables),
                    source_url=source_url,
                ))
            # Also keep concise descriptive windows containing runtime values.
            if self._mentions_runtime_value(window, runtime_variables):
                facts.append(NormalizedFact(
                    kind="supporting_statement",
                    label="statement",
                    value=window[:360],
                    context=window[:360],
                    confidence=0.72,
                    source_url=source_url,
                ))
        return facts

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

    def _label_from_context(self, context: str) -> str:
        before = context.split(":", 1)[0].strip()
        if before and len(before) <= 48:
            return before
        return "value"

    def _runtime_variables(self, state: dict[str, Any]) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        def add(name: str, value: Any) -> None:
            if value is None:
                return
            text = str(value).strip()
            if not text:
                return
            result.setdefault(name, [])
            if text not in result[name]:
                result[name].append(text)
            # Add simple date aliases without domain knowledge.
            m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", text)
            if m:
                y, mo, d = m.groups()
                for alias in (f"{int(mo)}/{int(d)}", f"{mo}/{d}", f"{int(mo)}-{int(d)}", f"{mo}-{d}", str(int(d)), f"{y}"):
                    if alias not in result[name]:
                        result[name].append(alias)
        # direct runtime_variables list
        for item in state.get("runtime_variables", []) if isinstance(state.get("runtime_variables"), list) else []:
            if isinstance(item, dict):
                name = str(item.get("name") or "value")
                for alias in item.get("aliases") or []:
                    add(name, alias)
        # common result sections and workflow params, without domain terms.
        for section_name in ("runtime_request_semantics", "parameters", "known", "input", "results"):
            section = state.get(section_name)
            self._collect_named_values(section, add)
        return result

    def _collect_named_values(self, value: Any, add) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(item, (str, int, float)):
                    add(str(key), item)
                elif isinstance(item, (dict, list)):
                    self._collect_named_values(item, add)
        elif isinstance(value, list):
            for item in value[:20]:
                self._collect_named_values(item, add)

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
