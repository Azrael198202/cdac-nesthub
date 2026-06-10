from __future__ import annotations

import re
from typing import Any

from ai_core.runtime.semantic.evidence_claim_ranker import EvidenceClaimRanker


class ClaimResolutionLayer:
    """Resolve extracted claims into verified facts.

    This layer is intentionally generic.  It resolves comparable numeric
    identifiers, structured measurements with units, and source-supported
    statements.  It does not contain domain-specific entity names.
    """

    NUMBER_WITH_UNIT = re.compile(
        r"(?P<label>[A-Za-z][A-Za-z _/-]{1,32}|[\u3040-\u30ff\u3400-\u9fff]{1,12})?\s*"
        r"(?P<value>-?\d+(?:\.\d+)?)\s*"
        r"(?P<unit>°\s?[CF]|℃|℉|%|percent|km/h|mph|m/s|hPa|mb|mm|cm|m|km|ft|in)(?![A-Za-z0-9])",
        re.IGNORECASE,
    )
    NEGATIVE_CONTEXT = re.compile(
        r"\b(beta|alpha|preview|candidate|development|devel|snapshot|nightly|test\s+new|testing|experimental|bugs?|issues?)\b",
        re.IGNORECASE,
    )
    POSITIVE_CONTEXT = re.compile(
        r"\b(stable|current|latest|general\s+availability|\bga\b|release|released|production)\b",
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        self.claim_ranker = EvidenceClaimRanker()

    def resolve(self, *, user_input: str, normalized_evidence: dict[str, Any]) -> dict[str, Any]:
        records = normalized_evidence.get("records") if isinstance(normalized_evidence, dict) else []
        records = [r for r in records if isinstance(r, dict)]
        comparable_claims = self.claim_ranker.extract_from_materials(records) if self._request_needs_comparable_identifier(user_input) else []
        comparable_claims = self._adjust_status_from_context(comparable_claims)
        comparable_claims = self._sort_claims(comparable_claims)
        best = comparable_claims[0] if comparable_claims else None

        measurements = self._extract_measurements(records)
        content_records = self._extract_content_records(records)
        statements = self._extract_supported_statements(records, best_claim=best)
        facts: list[dict[str, Any]] = []
        if best:
            facts.append({
                "kind": "resolved_comparable_identifier",
                "value": best.get("value"),
                "normalized": best.get("normalized"),
                "status": best.get("status"),
                "confidence": best.get("confidence"),
                "source_url": best.get("source_url"),
                "supporting_text": best.get("context"),
            })
        facts.extend(measurements[:8])
        facts.extend(content_records[:8])
        facts.extend(statements[:6])
        return {
            "facts": facts,
            "comparable_claims": comparable_claims,
            "measurements": measurements,
            "content_records": content_records,
            "statements": statements,
            "source_urls": normalized_evidence.get("source_urls", []) if isinstance(normalized_evidence, dict) else [],
            "passed": bool(facts),
        }

    def _request_needs_comparable_identifier(self, user_input: str) -> bool:
        text = str(user_input or "").casefold()
        return bool(re.search(r"\b(version|release|build|revision|edition|stable|current\s+version|latest\s+version)\b", text))

    def _adjust_status_from_context(self, claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
        adjusted: list[dict[str, Any]] = []
        for claim in claims:
            item = dict(claim)
            context = str(item.get("context") or "")
            if self.NEGATIVE_CONTEXT.search(context):
                item["status"] = "pre_release"
            elif self.POSITIVE_CONTEXT.search(context) and item.get("status") in {None, "", "unspecified", "mixed"}:
                item["status"] = "release"
            adjusted.append(item)
        return adjusted

    def _sort_claims(self, claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
        def key(item: dict[str, Any]) -> tuple[int, tuple[int, ...], int, float]:
            status = str(item.get("status") or "unspecified")
            status_rank = {"release": 4, "mixed": 2, "unspecified": 1, "pre_release": 0}.get(status, 1)
            normalized = tuple(int(x) for x in (item.get("normalized") or []) if isinstance(x, int))
            return (status_rank, normalized, int(item.get("source_rank") or 0), float(item.get("confidence") or 0.0))
        return sorted([c for c in claims if isinstance(c, dict)], key=key, reverse=True)[:24]

    def _extract_measurements(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for record in records:
            text = " ".join(str(record.get("text") or "").split())
            for match in self.NUMBER_WITH_UNIT.finditer(text[:1800]):
                label = " ".join(str(match.group("label") or "value").split())[-40:].strip() or "value"
                value = match.group("value")
                unit = match.group("unit").replace(" ", "")
                key = (label.casefold(), value, unit.casefold())
                if key in seen:
                    continue
                seen.add(key)
                start = max(0, match.start() - 120)
                end = min(len(text), match.end() + 160)
                out.append({
                    "kind": "resolved_measurement",
                    "label": label,
                    "value": value,
                    "unit": unit,
                    "source_url": record.get("url"),
                    "supporting_text": text[start:end],
                    "confidence": 0.72 + min(float(record.get("relevance_score") or 0.0), 0.2),
                })
                if len(out) >= 16:
                    return out
        return out

    def _extract_content_records(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for record in records:
            kind = str(record.get("kind") or record.get("source_type") or "")
            text = " ".join(str(record.get("text") or record.get("value") or "").split())
            title = " ".join(str(record.get("title") or "").split())
            if kind != "extracted_content_record" and float(record.get("relevance_score") or 0.0) < 0.5:
                continue
            value = title or text
            if len(value) < 20:
                continue
            key = value[:160].casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "kind": "source_supported_content_record",
                "title": value[:220],
                "value": text[:900] or value[:900],
                "source_url": record.get("url") or record.get("source_url"),
                "time_expression": record.get("time_expression") or "",
                "confidence": 0.68 + min(float(record.get("relevance_score") or 0.0), 0.25),
            })
            if len(out) >= 12:
                break
        return out

    def _extract_supported_statements(self, records: list[dict[str, Any]], *, best_claim: dict[str, Any] | None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        anchors = []
        if best_claim:
            anchors.append(str(best_claim.get("value") or ""))
        for record in records:
            text = " ".join(str(record.get("text") or record.get("title") or "").split())
            if not text:
                continue
            sentences = re.split(r"(?<=[.!?。！？])\s+", text)
            for sentence in sentences[:8]:
                clean = sentence.strip()[:420]
                if len(clean) < 24:
                    continue
                if anchors and not any(anchor and anchor in clean for anchor in anchors):
                    continue
                if not anchors and not re.search(r"\d", clean):
                    continue
                out.append({
                    "kind": "source_supported_statement",
                    "value": clean,
                    "source_url": record.get("url"),
                    "confidence": 0.62 + min(float(record.get("relevance_score") or 0.0), 0.2),
                })
                if len(out) >= 8:
                    return out
        return out
