from __future__ import annotations

import html
import json
import re
from dataclasses import asdict, dataclass
from typing import Any

try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception:  # pragma: no cover
    BeautifulSoup = None  # type: ignore


@dataclass
class EmbeddedStructureResult:
    status: str
    normalized_facts: list[dict[str, Any]]
    answer_material: str
    extraction_trace: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EmbeddedStructureExtractor:
    """Extract structured payloads embedded in rendered markup.

    This module is intentionally domain-neutral. It never checks task-specific
    vocabulary. It looks only for machine-readable structures: JSON script
    blocks, JSON-like data attributes, and scalar payloads embedded in DOM
    attributes. The caller provides runtime known values for alignment.
    """

    DATA_ATTR = re.compile(r"\b(data-[A-Za-z0-9_:\-]+)\s*=\s*(['\"])(.*?)\2", re.S)
    JSONISH = re.compile(r"^\s*(?:\{[\s\S]*\}|\[[\s\S]*\])\s*$")
    SCALAR_UNIT = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*([^\d\s]{1,12}|[A-Za-z%/]{1,16})?\s*$")

    def extract(self, *, document: dict[str, Any], known: dict[str, Any], max_facts: int = 120) -> EmbeddedStructureResult:
        markup = str(document.get("html_excerpt") or document.get("raw_html") or "")
        if not markup.strip():
            return EmbeddedStructureResult("empty", [], "", {"mode": "embedded_structure", "payload_count": 0})
        known_values = self._known_values(known)
        payloads = self._collect_payloads(markup)
        facts: list[dict[str, Any]] = []
        for source_label, payload in payloads:
            for path, value in self._walk(payload):
                if len(facts) >= max_facts:
                    break
                fact = self._fact(source_label=source_label, path=path, value=value, known_values=known_values, source_url=str(document.get("url") or ""))
                if fact:
                    facts.append(fact)
            if len(facts) >= max_facts:
                break
        facts = self._dedupe(facts)
        material = self._material(facts)
        return EmbeddedStructureResult(
            status="success" if facts else "no_facts",
            normalized_facts=facts[:max_facts],
            answer_material=material,
            extraction_trace={
                "mode": "embedded_structure_extraction",
                "payload_count": len(payloads),
                "fact_count": len(facts),
                "known_value_count": len(known_values),
            },
        )

    def _collect_payloads(self, markup: str) -> list[tuple[str, Any]]:
        payloads: list[tuple[str, Any]] = []
        if BeautifulSoup is not None:
            try:
                soup = BeautifulSoup(markup, "lxml")
            except Exception:
                soup = BeautifulSoup(markup, "html.parser")
            for idx, node in enumerate(soup.find_all("script")):
                typ = str(node.get("type") or "").casefold()
                text = str(node.string or node.get_text(" ") or "").strip()
                if not text:
                    continue
                if "json" in typ or self.JSONISH.match(text):
                    parsed = self._parse_jsonish(text)
                    if parsed is not None:
                        payloads.append((f"script[{idx}]", parsed))
            for idx, node in enumerate(soup.find_all(True)):
                attrs = getattr(node, "attrs", {}) or {}
                for name, value in attrs.items():
                    if not str(name).startswith("data-"):
                        continue
                    text = " ".join(str(x) for x in value) if isinstance(value, list) else str(value)
                    parsed = self._parse_jsonish(html.unescape(text))
                    if parsed is not None:
                        payloads.append((f"{getattr(node, 'name', 'node')}[{idx}].{name}", parsed))
                    else:
                        scalar = self._parse_scalar_sequence(text)
                        if scalar:
                            payloads.append((f"{getattr(node, 'name', 'node')}[{idx}].{name}", scalar))
        else:
            for idx, match in enumerate(self.DATA_ATTR.finditer(markup)):
                name = match.group(1)
                value = html.unescape(match.group(3))
                parsed = self._parse_jsonish(value)
                if parsed is not None:
                    payloads.append((f"attr[{idx}].{name}", parsed))
        return payloads[:80]

    def _parse_jsonish(self, text: str) -> Any | None:
        text = str(text or "").strip()
        if not text or len(text) > 1_500_000:
            return None
        try:
            return json.loads(text)
        except Exception:
            pass
        # Some attributes contain HTML-escaped JSON.
        try:
            return json.loads(html.unescape(text))
        except Exception:
            return None

    def _parse_scalar_sequence(self, text: str) -> dict[str, Any] | None:
        parts = [p.strip() for p in re.split(r"[;|,]", str(text or "")) if p.strip()]
        if len(parts) < 3 or len(parts) > 400:
            return None
        if not any(re.search(r"-?\d", p) for p in parts):
            return None
        return {"values": parts}

    def _walk(self, value: Any, path: str = ""):
        if isinstance(value, dict):
            for key, child in value.items():
                next_path = f"{path}.{key}" if path else str(key)
                yield from self._walk(child, next_path)
        elif isinstance(value, list):
            for idx, child in enumerate(value[:300]):
                next_path = f"{path}[{idx}]" if path else f"[{idx}]"
                yield from self._walk(child, next_path)
        else:
            if value is not None and str(value).strip():
                yield path, value

    def _fact(self, *, source_label: str, path: str, value: Any, known_values: set[str], source_url: str) -> dict[str, Any] | None:
        text = str(value).strip()
        if not text or len(text) > 600:
            return None
        label = self._label(path)
        target = self._matched_known(f"{source_label} {path} {text}".casefold(), known_values)
        unit = ""
        parsed: Any = value
        kind = "embedded_scalar"
        m = self.SCALAR_UNIT.match(text)
        if m:
            parsed = m.group(1)
            unit = m.group(2) or ""
            kind = "embedded_numeric"
        return {
            "kind": kind,
            "label": label,
            "value": parsed,
            "unit": unit,
            "target": target,
            "context": f"{source_label}:{path}"[:260],
            "confidence": 0.78 if target else 0.7,
            "source_url": source_url,
            "source_level": "embedded_machine_readable_structure",
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
                    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
                        values.add(s.replace("-", "/"))
                        values.add(s[5:].replace("-", "/"))
        add(known)
        return values

    def _matched_known(self, text: str, known_values: set[str]) -> str:
        for value in sorted(known_values, key=len, reverse=True):
            if value in text:
                return value
        return ""

    def _label(self, path: str) -> str:
        label = re.sub(r"\[\d+\]", "", str(path or "value")).split(".")[-1]
        label = re.sub(r"[^A-Za-z0-9_\-]+", "_", label).strip("_")
        return (label or "value")[:80]

    def _dedupe(self, facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for fact in facts:
            key = "|".join(str(fact.get(k, "")) for k in ("label", "value", "unit", "target", "context"))[:700].casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(fact)
        return out

    def _material(self, facts: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for fact in facts[:40]:
            target = str(fact.get("target") or "")
            label = str(fact.get("label") or "value")
            value = str(fact.get("value") or "") + str(fact.get("unit") or "")
            context = str(fact.get("context") or "")[:140]
            lines.append(" | ".join(x for x in (target, label, value.strip(), context) if x))
        return "\n".join(lines)
