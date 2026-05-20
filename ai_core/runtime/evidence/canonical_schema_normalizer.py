from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
_UNIT_RE = re.compile(r"(?:°\s*[A-Za-z]?|%|mm|cm|m|km/h|mph|m/s|hPa|kPa|kg|g|ml|L|l|円|¥|\$|€)", re.I)


@dataclass(frozen=True)
class CanonicalObservation:
    """Domain-neutral canonical observation used for cross-source comparison.

    The runtime must not embed task/business vocabulary here.  A canonical key
    is derived only from: target value, unit family, numeric shape, structural
    label tokens, and source identity.  This lets different sources converge
    even when they use different field names.
    """

    key: str
    target: str
    value: str
    unit: str
    numeric_value: float | None
    label_signature: str
    source_key: str
    confidence: float

    def to_fact_patch(self) -> dict[str, Any]:
        return {
            "canonical_key": self.key,
            "canonical_target": self.target,
            "canonical_unit_family": self._unit_family(self.unit),
            "canonical_label_signature": self.label_signature,
            "canonical_numeric_value": self.numeric_value,
        }

    @staticmethod
    def _unit_family(unit: str) -> str:
        text = str(unit or "").strip().lower().replace(" ", "")
        if not text:
            return "unitless"
        if text.startswith("°"):
            return "degree"
        if text in {"mm", "cm", "m"}:
            return "length"
        if text in {"km/h", "mph", "m/s"}:
            return "rate"
        if text in {"hpa", "kpa"}:
            return "pressure"
        if text == "%":
            return "ratio"
        if text in {"kg", "g"}:
            return "mass"
        if text in {"ml", "l"}:
            return "volume"
        if text in {"円", "¥", "$", "€"}:
            return "currency"
        return text[:24]


class CanonicalSchemaNormalizer:
    """Maps arbitrary source records to a generic canonical comparison schema."""

    MAX_LABEL_TOKENS = 4

    def normalize_facts(self, facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            obs = self.observation_from_fact(fact)
            if obs is None:
                continue
            patched = dict(fact)
            patched.update(obs.to_fact_patch())
            out.append(patched)
        return out

    def observation_from_fact(self, fact: dict[str, Any]) -> CanonicalObservation | None:
        value = str(fact.get("value") or "").strip()
        unit = str(fact.get("unit") or "").strip().replace(" ", "")
        context = str(fact.get("context") or "")
        if not value and not context:
            return None
        numeric_value = self._number(value) if value else self._number(context)
        if numeric_value is None:
            return None
        if not unit:
            unit = self._unit_from_text(value) or self._unit_from_text(context)
        if not unit:
            return None
        target = str(fact.get("target") or fact.get("canonical_target") or "").strip()
        label_signature = self._label_signature(str(fact.get("label") or fact.get("kind") or ""))
        unit_family = CanonicalObservation._unit_family(unit)
        key = "|".join([target or "untargeted", unit_family, label_signature or "generic"])
        source_key = str(fact.get("source_host") or fact.get("source_url") or "")
        try:
            confidence = float(fact.get("confidence") or 0.6)
        except Exception:
            confidence = 0.6
        return CanonicalObservation(
            key=key,
            target=target,
            value=value or str(numeric_value),
            unit=unit,
            numeric_value=numeric_value,
            label_signature=label_signature,
            source_key=source_key,
            confidence=confidence,
        )

    def _number(self, text: str) -> float | None:
        match = _NUMBER_RE.search(str(text or ""))
        if not match:
            return None
        try:
            return float(match.group(0))
        except Exception:
            return None

    def _unit_from_text(self, text: str) -> str:
        match = _UNIT_RE.search(str(text or ""))
        return match.group(0).replace(" ", "") if match else ""

    def _label_signature(self, label: str) -> str:
        text = re.sub(r"[^0-9A-Za-z_\-]+", " ", str(label or "").lower())
        tokens = [t for t in re.split(r"[_\-\s]+", text) if len(t) > 1 and not t.isdigit()]
        # Remove repeated technical carrier words while staying domain-neutral.
        ignored = {"value", "record", "field", "item", "data", "row", "col", "cell", "observed", "numeric"}
        tokens = [t for t in tokens if t not in ignored]
        return ".".join(tokens[: self.MAX_LABEL_TOKENS])


class SourceInvestigationReporter:
    """Builds a compact report of every source considered by DeepSearch."""

    def build(self, source_summaries: list[dict[str, Any]], *, consensus: dict[str, Any] | None = None) -> dict[str, Any]:
        consensus = consensus if isinstance(consensus, dict) else {}
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in source_summaries:
            if not isinstance(raw, dict):
                continue
            url = str(raw.get("url") or raw.get("source_url") or "").strip()
            host = str(raw.get("host") or "").strip()
            key = url or host
            if not key or key in seen:
                continue
            seen.add(key)
            fact_count = self._int(raw.get("fact_count"))
            score = self._float(raw.get("score"))
            layers = raw.get("layers") if isinstance(raw.get("layers"), list) else []
            status = "accepted_candidate" if fact_count > 0 and score >= 0.35 else "reviewed_no_usable_material"
            reason = "materialized_measurements_available" if status == "accepted_candidate" else "insufficient_target_aligned_material"
            items.append({
                "url": url,
                "host": host,
                "title": str(raw.get("title") or "")[:160],
                "status": status,
                "reason": reason,
                "score": round(score, 3),
                "fact_count": fact_count,
                "layers": [str(x) for x in layers[:8]],
            })
        return {
            "status": "completed",
            "source_count": len(items),
            "sources": items,
            "consensus_status": "passed" if consensus.get("passed") is True else "insufficient",
            "consensus_reason": consensus.get("reason") or consensus.get("quality", {}).get("reason") if isinstance(consensus.get("quality"), dict) else "",
        }

    def _int(self, value: Any) -> int:
        try:
            return int(value or 0)
        except Exception:
            return 0

    def _float(self, value: Any) -> float:
        try:
            return float(value or 0.0)
        except Exception:
            return 0.0
