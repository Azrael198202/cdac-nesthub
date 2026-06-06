from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class StructuredExtractionResult:
    status: str
    normalized_facts: list[dict[str, Any]]
    answer_material: str
    source_summaries: list[dict[str, Any]]
    extraction_trace: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class StructuredResponseExtractor:
    """Extract compact facts from browser-captured structured responses.

    It is generic: facts come from JSON paths, scalar values, units, timestamps,
    arrays and objects. Alignment is based only on runtime-provided known values.
    """

    VALUE_WITH_UNIT = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*([^\d\s]{1,12}|[A-Za-z%/]{1,16})?\s*$")
    DATE_LIKE = re.compile(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:[T\s]\d{1,2}:\d{2}(?::\d{2})?)?\b")

    def extract(self, *, browser_document: dict[str, Any], known: dict[str, Any], max_facts: int = 80) -> StructuredExtractionResult:
        responses = browser_document.get("browser_network_responses")
        if not isinstance(responses, list):
            responses = []
        known_values = self._known_values(known)
        facts: list[dict[str, Any]] = []
        source_summaries: list[dict[str, Any]] = []
        for response in responses:
            if not isinstance(response, dict):
                continue
            json_data = response.get("json_data")
            body_text = str(response.get("body_text") or "")
            if json_data is None and body_text:
                try:
                    json_data = json.loads(body_text)
                except Exception:
                    json_data = None
            if json_data is None:
                continue
            flat = list(self._walk_json(json_data))
            aligned = self._alignment_score(flat=flat, known_values=known_values)
            source_summaries.append({
                "url": response.get("url"),
                "status": response.get("status"),
                "content_type": response.get("content_type"),
                "scalar_count": len(flat),
                "alignment_score": aligned,
            })
            for path, value in flat:
                if len(facts) >= max_facts:
                    break
                fact = self._to_fact(path=path, value=value, source_url=str(response.get("url") or ""), known_values=known_values, source_alignment=aligned)
                if fact:
                    facts.append(fact)
            if len(facts) >= max_facts:
                break
        facts = self._dedupe_facts(facts)
        material = self._material(facts)
        return StructuredExtractionResult(
            status="success" if facts else "no_structured_facts",
            normalized_facts=facts[:max_facts],
            answer_material=material,
            source_summaries=source_summaries,
            extraction_trace={
                "mode": "browser_network_structured_response_extraction",
                "response_count": len(responses),
                "structured_source_count": len(source_summaries),
                "fact_count": len(facts),
                "known_value_count": len(known_values),
            },
        )

    def _walk_json(self, value: Any, path: str = ""):
        if isinstance(value, dict):
            for k, v in value.items():
                key = str(k)
                next_path = f"{path}.{key}" if path else key
                yield from self._walk_json(v, next_path)
        elif isinstance(value, list):
            for i, v in enumerate(value[:200]):
                next_path = f"{path}[{i}]" if path else f"[{i}]"
                yield from self._walk_json(v, next_path)
        else:
            if value is None:
                return
            text = str(value).strip()
            if text:
                yield path, value

    def _to_fact(self, *, path: str, value: Any, source_url: str, known_values: set[str], source_alignment: float) -> dict[str, Any] | None:
        text = str(value).strip()
        if not text:
            return None
        path_text = str(path or "value")
        lower = f"{path_text} {text}".casefold()
        target = self._matched_known(lower, known_values)
        kind = "structured_value"
        unit = ""
        parsed_value: Any = value
        match = self.VALUE_WITH_UNIT.match(text)
        if match:
            parsed_value = match.group(1)
            unit = match.group(2) or ""
            kind = "numeric_value"
        elif self.DATE_LIKE.search(text):
            kind = "temporal_value"
        elif isinstance(value, bool):
            kind = "boolean_value"
        elif isinstance(value, (int, float)):
            kind = "numeric_value"
        confidence = 0.68 + min(source_alignment, 0.25)
        if target:
            confidence += 0.07
        return {
            "kind": kind,
            "label": self._label_from_path(path_text),
            "value": parsed_value,
            "unit": unit,
            "target": target,
            "context": path_text,
            "confidence": round(min(confidence, 0.98), 3),
            "source_url": source_url,
            "source_level": "browser_network_structured_response",
            "structured": True,
        }

    def _known_values(self, known: dict[str, Any]) -> set[str]:
        values: set[str] = set()
        def add(v: Any) -> None:
            if isinstance(v, dict):
                for x in v.values():
                    add(x)
            elif isinstance(v, (list, tuple, set)):
                for x in v:
                    add(x)
            else:
                s = str(v).strip().casefold()
                if len(s) >= 2:
                    values.add(s)
                    # Add common slash date variant while staying generic.
                    if re.match(r"\d{4}-\d{2}-\d{2}$", s):
                        values.add(s.replace("-", "/"))
                        values.add(s[5:].replace("-", "/"))
        add(known)
        return values

    def _alignment_score(self, *, flat: list[tuple[str, Any]], known_values: set[str]) -> float:
        if not known_values:
            return 0.05
        hay = "\n".join(f"{p} {v}" for p, v in flat[:1000]).casefold()
        matched = sum(1 for value in known_values if value in hay)
        return min(1.0, matched / max(1, len(known_values)))

    def _matched_known(self, text: str, known_values: set[str]) -> str:
        for value in sorted(known_values, key=len, reverse=True):
            if value and value in text:
                return value
        return ""

    def _label_from_path(self, path: str) -> str:
        label = re.sub(r"\[\d+\]", "", path).split(".")[-1] or "value"
        label = re.sub(r"[^A-Za-z0-9_\-]+", "_", label).strip("_")
        return label[:80] or "value"

    def _dedupe_facts(self, facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for fact in facts:
            key = "|".join(str(fact.get(k, "")) for k in ("label", "value", "unit", "target", "source_url"))[:500].casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(fact)
        return out

    def _material(self, facts: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for fact in facts[:24]:
            target = str(fact.get("target") or "")
            label = str(fact.get("label") or "value")
            value = str(fact.get("value") or "")
            unit = str(fact.get("unit") or "")
            context = str(fact.get("context") or "")[:160]
            lines.append(" | ".join(x for x in [target, label, (value + unit).strip(), context] if x))
        return "\n".join(lines)
