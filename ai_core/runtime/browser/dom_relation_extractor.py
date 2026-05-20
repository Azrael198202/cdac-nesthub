from __future__ import annotations

import html
import re
from dataclasses import asdict, dataclass
from typing import Any

try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception:  # pragma: no cover
    BeautifulSoup = None  # type: ignore


@dataclass
class DomRelationExtractionResult:
    status: str
    normalized_facts: list[dict[str, Any]]
    answer_material: str
    extraction_trace: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DomRelationExtractor:
    """Extract relation-like cells from rendered DOM without domain rules.

    The parser detects generic table/list structures and preserves row/column
    relationships. It avoids free-text summarization and does not inspect
    task-specific vocabulary.
    """

    VALUE_UNIT = re.compile(r"(-?\d+(?:\.\d+)?)\s*([A-Za-z%/]+|°[A-Za-z]?|[^\d\s]{1,8})?\b")

    def extract(self, *, document: dict[str, Any], known: dict[str, Any], max_facts: int = 160) -> DomRelationExtractionResult:
        markup = str(document.get("html_excerpt") or "")
        visible = str(document.get("visible_text_excerpt") or document.get("text_excerpt") or "")
        source_url = str(document.get("url") or "")
        known_values = self._known_values(known)
        facts: list[dict[str, Any]] = []
        if markup and BeautifulSoup is not None:
            facts.extend(self._extract_tables(markup=markup, source_url=source_url, known_values=known_values, max_facts=max_facts))
        if len(facts) < max_facts and visible:
            facts.extend(self._extract_dense_sequences(text=visible, source_url=source_url, known_values=known_values, max_facts=max_facts - len(facts)))
        facts = self._dedupe(facts)[:max_facts]
        material = self._material(facts)
        return DomRelationExtractionResult(
            status="success" if facts else "no_relations",
            normalized_facts=facts,
            answer_material=material,
            extraction_trace={
                "mode": "dom_relation_extraction",
                "fact_count": len(facts),
                "known_value_count": len(known_values),
                "source_level": "rendered_dom_relation",
            },
        )

    def _extract_tables(self, *, markup: str, source_url: str, known_values: set[str], max_facts: int) -> list[dict[str, Any]]:
        facts: list[dict[str, Any]] = []
        try:
            soup = BeautifulSoup(markup, "lxml")
        except Exception:
            soup = BeautifulSoup(markup, "html.parser")
        for table_index, table in enumerate(soup.find_all("table")[:24]):
            rows = []
            for tr in table.find_all("tr")[:120]:
                cells = []
                for cell in tr.find_all(["th", "td"], recursive=False):
                    text = " ".join(cell.get_text(" ").split())
                    attrs = self._attrs(cell)
                    cells.append({"text": text, "tag": getattr(cell, "name", ""), "attrs": attrs})
                if cells:
                    rows.append(cells)
            if not rows:
                continue
            headers = self._headers(rows)
            for row_index, row in enumerate(rows[1:] if headers else rows):
                row_label = row[0]["text"] if row else ""
                for cell_index, cell in enumerate(row):
                    text = cell.get("text") or ""
                    if not self._informative(text):
                        continue
                    column = headers[cell_index] if cell_index < len(headers) else ""
                    context = self._context(table_index, row_index, cell_index, row_label, column, cell.get("attrs") or {})
                    for fact in self._facts_from_text(text=text, context=context, source_url=source_url, known_values=known_values, source_level="rendered_dom_table_cell"):
                        facts.append(fact)
                        if len(facts) >= max_facts:
                            return facts
        return facts

    def _extract_dense_sequences(self, *, text: str, source_url: str, known_values: set[str], max_facts: int) -> list[dict[str, Any]]:
        text = " ".join(str(text or "").split())
        facts: list[dict[str, Any]] = []
        # Generic pattern: a short label followed by one or more scalar values.
        for index, match in enumerate(re.finditer(r"(?:^|[\n\.])\s*([^\n\.]{2,80}?)\s+((-?\d+(?:\.\d+)?\s*(?:[A-Za-z%/]+|°[A-Za-z]?|[^\d\s]{1,8})?\s*){1,6})", text[:40000])):
            label = " ".join(match.group(1).split())[:80]
            value_text = match.group(2)
            context = f"sequence[{index}] {label}"
            for fact in self._facts_from_text(text=value_text, context=context, source_url=source_url, known_values=known_values, source_level="rendered_text_sequence"):
                facts.append(fact)
                if len(facts) >= max_facts:
                    return facts
        return facts

    def _facts_from_text(self, *, text: str, context: str, source_url: str, known_values: set[str], source_level: str) -> list[dict[str, Any]]:
        facts: list[dict[str, Any]] = []
        lower = f"{context} {text}".casefold()
        target = self._matched_known(lower, known_values)
        for idx, m in enumerate(self.VALUE_UNIT.finditer(text)):
            value = m.group(1)
            unit = m.group(2) or ""
            if not value:
                continue
            facts.append({
                "kind": "relational_numeric_cell",
                "label": self._label(context, idx),
                "value": value,
                "unit": unit,
                "target": target,
                "context": context[:260],
                "confidence": 0.82 if target else 0.74,
                "source_url": source_url,
                "source_level": source_level,
                "structured": True,
            })
            if len(facts) >= 5:
                break
        if not facts and len(text) <= 240 and any(k in lower for k in known_values):
            facts.append({
                "kind": "relational_text_cell",
                "label": self._label(context, 0),
                "value": text[:240],
                "unit": "",
                "target": target,
                "context": context[:260],
                "confidence": 0.72 if target else 0.64,
                "source_url": source_url,
                "source_level": source_level,
                "structured": True,
            })
        return facts

    def _headers(self, rows: list[list[dict[str, Any]]]) -> list[str]:
        if not rows:
            return []
        first = rows[0]
        if any(cell.get("tag") == "th" for cell in first):
            return [str(cell.get("text") or "")[:80] for cell in first]
        if len(rows) > 1 and len(first) >= len(rows[1]):
            numeric_ratio = sum(1 for c in first if re.search(r"-?\d", str(c.get("text") or ""))) / max(1, len(first))
            second_numeric = sum(1 for c in rows[1] if re.search(r"-?\d", str(c.get("text") or ""))) / max(1, len(rows[1]))
            if numeric_ratio < second_numeric:
                return [str(cell.get("text") or "")[:80] for cell in first]
        return []

    def _attrs(self, cell: Any) -> dict[str, str]:
        out: dict[str, str] = {}
        for key, value in (getattr(cell, "attrs", {}) or {}).items():
            if str(key).startswith("data-") or key in {"class", "id", "headers"}:
                out[str(key)] = " ".join(str(x) for x in value) if isinstance(value, list) else str(value)
        return out

    def _context(self, table_index: int, row_index: int, cell_index: int, row_label: str, column: str, attrs: dict[str, str]) -> str:
        attr_text = " ".join(f"{k}={v}" for k, v in attrs.items() if v)[:120]
        parts = [f"table[{table_index}]", f"row[{row_index}]", f"cell[{cell_index}]", row_label[:80], column[:80], attr_text]
        return " | ".join(p for p in parts if p)

    def _informative(self, text: str) -> bool:
        text = str(text or "").strip()
        if len(text) < 2:
            return False
        if len(text) > 800:
            return False
        return bool(re.search(r"-?\d", text) or len(text.split()) >= 2)

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
            if value and value in text:
                return value
        return ""

    def _label(self, context: str, index: int) -> str:
        bits = [b.strip() for b in context.split("|") if b.strip()]
        label = bits[-1] if bits else f"value_{index + 1}"
        label = re.sub(r"[^A-Za-z0-9_\-]+", "_", label).strip("_")
        return (label or f"value_{index + 1}")[:80]

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
        for fact in facts[:48]:
            target = str(fact.get("target") or "")
            label = str(fact.get("label") or "value")
            value = (str(fact.get("value") or "") + str(fact.get("unit") or "")).strip()
            context = str(fact.get("context") or "")[:160]
            lines.append(" | ".join(x for x in (target, label, value, context) if x))
        return "\n".join(lines)
