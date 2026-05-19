from __future__ import annotations

import html
import re
from dataclasses import dataclass, asdict
from html.parser import HTMLParser
from typing import Any

from ai_core.runtime.temporal import DateAliasGenerator
from ai_core.presentation.date_aligned_record_extractor import DateAlignedRecordExtractor


@dataclass
class EvidenceRecord:
    kind: str
    label: str
    value: str
    context: str = ""
    unit: str = ""
    target: str = ""
    confidence: float = 0.7
    source_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class _VisibleBlockParser(HTMLParser):
    """Extract compact visible blocks without relying on any domain words."""

    SKIP_TAGS = {"script", "style", "noscript", "svg", "canvas"}
    BLOCK_TAGS = {"tr", "li", "p", "section", "article", "div", "td", "th"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[str] = []
        self._stack: list[tuple[str, list[str]]] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in self.BLOCK_TAGS:
            self._stack.append((tag, []))
        attr_map = {str(k).lower(): str(v) for k, v in attrs if v is not None}
        for key in ("title", "alt", "aria-label", "datetime"):
            value = attr_map.get(key)
            if value:
                self._append(value)
        for key, value in attr_map.items():
            if key.startswith("data-") and value and len(value) <= 96:
                self._append(value)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if self._stack and self._stack[-1][0] == tag:
            _, parts = self._stack.pop()
            text = self._compact(" ".join(parts))
            if text:
                self.blocks.append(text)
                self._append(text)

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        self._append(data)

    def _append(self, value: str) -> None:
        text = self._compact(value)
        if not text:
            return
        if self._stack:
            self._stack[-1][1].append(text)
        else:
            self.blocks.append(text)

    def _compact(self, value: str) -> str:
        return " ".join(html.unescape(str(value or "")).split())


class RuntimeEvidenceNormalizer:
    """Create compact, target-aligned evidence without domain-specific rules.

    The normalizer only uses runtime-provided variables and structural signals:
    aliases, rows, repeated blocks, numeric values, units, and source metadata.
    """

    VALUE_WITH_UNIT = re.compile(
        r"[-+]?\d+(?:\.\d+)?\s*(?:°\s*[CFcf]?|%|mm|cm|m|km/h|mph|hPa|kPa|kg|g|ml|L|l|円|¥|\$|€)"
    )
    NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?")
    ISO_DATE = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$")

    def __init__(self) -> None:
        self.alias_generator = DateAliasGenerator()
        self.aligned_extractor = DateAlignedRecordExtractor()

    def normalize(
        self,
        *,
        text: str,
        known: dict[str, Any],
        source_url: str = "",
        state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        clean_blocks = self._extract_blocks(text)
        variables = self._runtime_variables(known=known, state=state or {})
        aligned_records = self._aligned_records(blocks=clean_blocks, variables=variables, source_url=source_url, state=state or {})
        generic_records = self._generic_records(blocks=clean_blocks, variables=variables, source_url=source_url)
        records = self._dedupe_records(aligned_records + generic_records)
        selected_blocks = self._selected_blocks(blocks=clean_blocks, variables=variables)
        quality = self._quality(records=records, blocks=selected_blocks, variables=variables)
        material = self._material(records=records, selected_blocks=selected_blocks)
        return {
            "normalized_facts": [r.to_dict() for r in records[:24]],
            "selected_evidence_blocks": selected_blocks[:16],
            "answer_material": material,
            "answer_material_quality": quality,
        }

    def _runtime_variables(self, *, known: dict[str, Any], state: dict[str, Any]) -> dict[str, list[str]]:
        variables: dict[str, list[str]] = {}

        def add(name: str, value: Any) -> None:
            aliases = self.alias_generator.aliases_for(value, runtime_state=state)
            if not aliases:
                return
            bucket = variables.setdefault(str(name or "value"), [])
            for alias in aliases:
                text = str(alias or "").strip()
                if text and text not in bucket:
                    bucket.append(text)

        for key, value in known.items():
            add(str(key), value)
        for key, aliases in self.alias_generator.aliases_from_state(state).items():
            for alias in aliases:
                add(key, alias)
        return variables

    def _extract_blocks(self, text: str) -> list[str]:
        raw = str(text or "")
        if not raw.strip():
            return []
        blocks: list[str] = []
        if "<" in raw and ">" in raw:
            parser = _VisibleBlockParser()
            try:
                parser.feed(raw)
                blocks.extend(parser.blocks)
            except Exception:
                blocks.append(self._strip_markup(raw))
        else:
            blocks.extend(re.split(r"[\r\n]+", raw))
            blocks.extend(re.split(r"(?<=[。.!?])\s+", raw))
        compacted = []
        for block in blocks:
            text = self._compact(self._strip_markup(block))
            if not text:
                continue
            if len(text) < 3:
                continue
            compacted.append(text[:1400])
        return self._dedupe_text(compacted)[:1200]

    def _aligned_records(
        self,
        *,
        blocks: list[str],
        variables: dict[str, list[str]],
        source_url: str,
        state: dict[str, Any],
    ) -> list[EvidenceRecord]:
        records: list[EvidenceRecord] = []
        joined = " ".join(blocks[:600])
        for item in self.aligned_extractor.extract(text=joined, runtime_variables=variables, source_url=source_url, runtime_state=state):
            if not isinstance(item, dict):
                continue
            value = str(item.get("value") or item.get("context") or "").strip()
            if not value:
                continue
            records.append(EvidenceRecord(
                kind="aligned_record",
                label=str(item.get("label") or "target_record"),
                value=value,
                context=str(item.get("context") or value),
                target=str(item.get("target") or ""),
                confidence=float(item.get("confidence") or 0.82),
                source_url=source_url,
            ))
        return records

    def _generic_records(self, *, blocks: list[str], variables: dict[str, list[str]], source_url: str) -> list[EvidenceRecord]:
        records: list[EvidenceRecord] = []
        selected = self._selected_blocks(blocks=blocks, variables=variables)
        for block in selected[:24]:
            for match in self.VALUE_WITH_UNIT.finditer(block):
                value_unit = match.group(0).strip()
                value, unit = self._split_value_unit(value_unit)
                context = self._context(block, match.start(), match.end())
                if self._looks_noisy_context(context):
                    continue
                records.append(EvidenceRecord(
                    kind="observed_value",
                    label=self._label_from_context(context),
                    value=value,
                    unit=unit,
                    context=context,
                    confidence=self._block_score(block, variables),
                    source_url=source_url,
                ))
        return records

    def _selected_blocks(self, *, blocks: list[str], variables: dict[str, list[str]]) -> list[str]:
        scored: list[tuple[float, str]] = []
        for block in blocks:
            score = self._block_score(block, variables)
            if score >= 0.45:
                scored.append((score, block))
        scored.sort(key=lambda item: (-item[0], len(item[1])))
        return [text for _, text in scored]

    def _block_score(self, block: str, variables: dict[str, list[str]]) -> float:
        text = self._compact(block)
        if not text:
            return 0.0
        score = 0.0
        matches = self._matched_alias_count(text, variables)
        unit_count = len(self.VALUE_WITH_UNIT.findall(text))
        number_count = len(self.NUMBER.findall(text))
        score += min(matches, 4) * 0.22
        score += min(unit_count, 5) * 0.12
        score += min(number_count, 8) * 0.015
        if 20 <= len(text) <= 420:
            score += 0.12
        if len(text) > 900:
            score -= 0.28
        if self._looks_like_repeated_index_strip(text):
            score -= 0.45
        return max(0.0, min(0.99, score))

    def _matched_alias_count(self, text: str, variables: dict[str, list[str]]) -> int:
        hay = text.casefold()
        count = 0
        for aliases in variables.values():
            strong_aliases = [a for a in aliases if len(str(a).strip()) >= 3]
            for alias in strong_aliases[:16]:
                if str(alias).casefold() in hay:
                    count += 1
                    break
        return count

    def _quality(self, *, records: list[EvidenceRecord], blocks: list[str], variables: dict[str, list[str]]) -> dict[str, Any]:
        target_count = sum(1 for aliases in variables.values() for alias in aliases if self.ISO_DATE.match(str(alias)))
        aligned_targets = {r.target for r in records if r.target}
        unit_records = [r for r in records if r.unit]
        long_blocks = [b for b in blocks if len(b) > 700]
        return {
            "passed": bool(records) and (bool(unit_records) or bool(aligned_targets)),
            "record_count": len(records),
            "unit_record_count": len(unit_records),
            "target_count": target_count,
            "aligned_target_count": len(aligned_targets),
            "long_block_count": len(long_blocks),
            "raw_evidence_omitted": True,
            "domain_specific_rules_used": False,
        }

    def _material(self, *, records: list[EvidenceRecord], selected_blocks: list[str]) -> str:
        lines: list[str] = []
        aligned = [r for r in records if r.kind == "aligned_record"]
        if aligned:
            for record in aligned[:8]:
                lines.append(record.value)
        else:
            for block in selected_blocks[:3]:
                lines.append(block[:420])
        return "\n".join(self._dedupe_text([self._compact(x) for x in lines if x]))[:1800]

    def _split_value_unit(self, value_unit: str) -> tuple[str, str]:
        match = re.match(r"^([-+]?\d+(?:\.\d+)?)\s*(.*)$", value_unit.strip())
        if not match:
            return value_unit, ""
        return match.group(1), match.group(2).replace(" ", "")

    def _context(self, text: str, start: int, end: int) -> str:
        return self._compact(text[max(0, start - 80): min(len(text), end + 140)])[:360]

    def _label_from_context(self, context: str) -> str:
        before = context[:120]
        words = re.findall(r"[^\W\d_][^\W\d_\-]{1,24}", before, flags=re.UNICODE)
        if not words:
            return "value"
        return "_".join(words[-3:])[:64]

    def _looks_noisy_context(self, context: str) -> bool:
        text = self._compact(context)
        if len(text) > 420:
            return True
        if self._looks_like_repeated_index_strip(text):
            return True
        return False

    def _looks_like_repeated_index_strip(self, text: str) -> bool:
        sample = str(text or "")[:320]
        short_numbers = re.findall(r"(?<![\d.])\d{1,2}(?![\d.])", sample)
        separators = sample.count("|") + sample.count("/") + sample.count("-")
        unit_count = len(self.VALUE_WITH_UNIT.findall(sample))
        return len(short_numbers) >= 10 and unit_count <= 1 and separators >= 3

    def _strip_markup(self, text: str) -> str:
        value = re.sub(r"<script\b[^>]*>.*?</script>", " ", str(text or ""), flags=re.I | re.S)
        value = re.sub(r"<style\b[^>]*>.*?</style>", " ", value, flags=re.I | re.S)
        value = re.sub(r"<[^>]+>", " ", value)
        return html.unescape(value)

    def _compact(self, text: str) -> str:
        return " ".join(html.unescape(str(text or "")).split())

    def _dedupe_text(self, items: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for item in items:
            text = self._compact(item)
            key = text.casefold()
            if not text or key in seen:
                continue
            seen.add(key)
            result.append(text)
        return result

    def _dedupe_records(self, records: list[EvidenceRecord]) -> list[EvidenceRecord]:
        result: list[EvidenceRecord] = []
        seen: set[str] = set()
        for record in records:
            key = "|".join([record.kind, record.label, record.value, record.unit, record.context[:160], record.target]).casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(record)
        result.sort(key=lambda r: (-float(r.confidence or 0), r.target, r.label))
        return result[:32]
