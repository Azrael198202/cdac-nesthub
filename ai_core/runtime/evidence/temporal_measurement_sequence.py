from __future__ import annotations

import re
from typing import Any


class TemporalMeasurementSequenceExtractor:
    """Extract compact temporal measurement rows from structured page text.

    Domain-neutral: it only recognizes timestamps followed by numeric values with
    units/directions/probabilities. It does not know any business category.
    """

    TIME_TOKEN = re.compile(r"\b\d{1,2}:\d{2}(?:\s+tomorrow)?\b", re.I)
    DATE_TOKEN = re.compile(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b")
    VALUE_UNIT = re.compile(r"(-?\d+(?:\.\d+)?)\s*(°C|°F|mm|cm|%|km/h|mph|hPa|kPa|m/s)\b", re.I)
    DIRECTION = re.compile(r"\b(N|NE|E|SE|S|SW|W|NW)\b")
    MEASURE_CELL = re.compile(
        r"(-?\d+(?:\.\d+)?)\s*(°C|°F)\s+"
        r"(-?\d+(?:\.\d+)?)\s*(mm|cm)\s+"
        r"(-?\d+(?:\.\d+)?)\s*%"
        r"(?:\s+(N|NE|E|SE|S|SW|W|NW))?"
        r"(?:\s+(-?\d+(?:\.\d+)?)\s*(km/h|mph|m/s))?",
        re.I,
    )

    def extract(self, *, text: str, known: dict[str, Any], source_url: str = "", max_rows: int = 48) -> dict[str, Any]:
        text = " ".join(str(text or "").split())
        if not text:
            return {"normalized_facts": [], "answer_material": "", "quality": {"passed": False, "reason": "empty_text"}}
        known_dates = self._known_dates(known)
        rows = self._extract_rows(text, known_dates=known_dates, max_rows=max_rows)
        if not rows:
            return {"normalized_facts": [], "answer_material": "", "quality": {"passed": False, "reason": "no_temporal_measurement_rows"}}
        facts: list[dict[str, Any]] = []
        for row in rows:
            for idx, measure in enumerate(row.get("measurements") or []):
                facts.append({
                    "kind": "temporal_measurement",
                    "label": measure.get("label") or f"measurement_{idx + 1}",
                    "value": measure.get("value"),
                    "unit": measure.get("unit") or "",
                    "target": row.get("target_date") or row.get("time") or "",
                    "context": row.get("summary") or "",
                    "confidence": 0.86,
                    "source_url": source_url,
                    "source_level": "browser_or_dom_temporal_sequence",
                    "structured": True,
                })
        material_lines = []
        for row in rows[:24]:
            material_lines.append(row.get("summary") or "")
        target_hits = len({r.get("target_date") for r in rows if r.get("target_date")})
        quality = {
            "passed": bool(rows and (not known_dates or target_hits > 0)),
            "score": min(0.95, 0.65 + min(len(rows), 12) * 0.025 + target_hits * 0.08),
            "record_count": len(rows),
            "unit_record_count": len(facts),
            "target_count": len(known_dates),
            "aligned_target_count": target_hits,
            "domain_specific_rules_used": False,
            "source_level": "browser_or_dom_temporal_sequence",
        }
        return {
            "normalized_facts": facts[:max_rows * 4],
            "answer_material": "\n".join(x for x in material_lines if x),
            "quality": quality,
            "rows": rows,
        }

    def _known_dates(self, known: dict[str, Any]) -> list[str]:
        values: list[str] = []
        def add(v: Any) -> None:
            if isinstance(v, dict):
                for x in v.values(): add(x)
            elif isinstance(v, (list, tuple, set)):
                for x in v: add(x)
            else:
                s=str(v).strip()
                if self.DATE_TOKEN.fullmatch(s):
                    values.append(s.replace('-', '/'))
        add(known)
        out=[]
        for v in values:
            if v not in out: out.append(v)
        return out

    def _extract_rows(self, text: str, *, known_dates: list[str], max_rows: int) -> list[dict[str, Any]]:
        table_rows = self._extract_table_rows(text, known_dates=known_dates, max_rows=max_rows)
        if table_rows:
            return table_rows
        matches=list(self.TIME_TOKEN.finditer(text))
        rows=[]
        if not matches:
            # Daily compact rows: date + short condition text + high/low values.
            for m in self.DATE_TOKEN.finditer(text):
                window=text[m.start():m.start()+180]
                measures=self._measurements(window)
                if measures:
                    rows.append(self._row(time=m.group(0), target_date=m.group(0).replace('-', '/'), measurements=measures, raw=window))
                    if len(rows)>=max_rows: break
            return rows
        for i,m in enumerate(matches):
            start=m.end()
            end=matches[i+1].start() if i+1 < len(matches) else min(len(text), start+120)
            window=text[start:end]
            measures=self._measurements(window)
            if not measures:
                continue
            token=m.group(0)
            target=""
            # Generic mapping: explicit "tomorrow" maps to the second known date; otherwise first known date.
            if "tomorrow" in token.casefold() and len(known_dates)>=2:
                target=known_dates[1]
            elif known_dates:
                target=known_dates[0]
            rows.append(self._row(time=token, target_date=target, measurements=measures, raw=window))
            if len(rows)>=max_rows:
                break
        return rows

    def _extract_table_rows(self, text: str, *, known_dates: list[str], max_rows: int) -> list[dict[str, Any]]:
        times = [m.group(0) for m in self.TIME_TOKEN.finditer(text)]
        if len(times) < 3:
            return []
        # Start after the first dense time header block. This keeps the parser
        # generic while avoiding latitude/altitude/current metadata.
        first_matches = list(self.TIME_TOKEN.finditer(text))[:min(len(times), 48)]
        header_end = first_matches[-1].end()
        tail = text[header_end: header_end + 6000]
        cells = list(self.MEASURE_CELL.finditer(tail))
        if not cells:
            return []
        rows=[]
        for i, cell in enumerate(cells[:min(len(times), max_rows)]):
            token = times[i] if i < len(times) else ""
            target=""
            if "tomorrow" in token.casefold() and len(known_dates)>=2:
                target=known_dates[1]
            elif known_dates:
                target=known_dates[0]
            measures=[
                {"label":"degree_value", "value":cell.group(1), "unit":cell.group(2)},
                {"label":"amount_value", "value":cell.group(3), "unit":cell.group(4)},
                {"label":"percent_value", "value":cell.group(5), "unit":"%"},
            ]
            if cell.group(6):
                measures.append({"label":"direction", "value":cell.group(6).upper(), "unit":""})
            if cell.group(7):
                measures.append({"label":"speed_value", "value":cell.group(7), "unit":cell.group(8) or ""})
            rows.append(self._row(time=token, target_date=target, measurements=measures, raw=cell.group(0)))
        return rows

    def _measurements(self, text: str) -> list[dict[str, Any]]:
        measures=[]
        for j,m in enumerate(self.VALUE_UNIT.finditer(text)):
            label = self._generic_label(str(m.group(2) or ''), j)
            measures.append({"label": label, "value": m.group(1), "unit": m.group(2)})
            if len(measures)>=5:
                break
        d=self.DIRECTION.search(text)
        if d:
            measures.append({"label":"direction", "value":d.group(1), "unit":""})
        return measures

    def _generic_label(self, unit: str, index: int) -> str:
        u=unit.casefold()
        if u in {'°c','°f'}:
            return 'degree_value'
        if u in {'mm','cm'}:
            return 'amount_value'
        if u == '%':
            return 'percent_value'
        if u in {'km/h','mph','m/s'}:
            return 'speed_value'
        if u in {'hpa','kpa'}:
            return 'pressure_value'
        return f'numeric_value_{index+1}'

    def _row(self, *, time: str, target_date: str, measurements: list[dict[str, Any]], raw: str) -> dict[str, Any]:
        parts=[]
        for m in measurements:
            parts.append(f"{m.get('label')}: {m.get('value')}{m.get('unit') or ''}")
        prefix = f"{target_date} {time}".strip()
        return {"time": time, "target_date": target_date, "measurements": measurements, "summary": f"{prefix} - " + "; ".join(parts), "raw": raw[:300]}
