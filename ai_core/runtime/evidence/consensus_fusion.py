from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass
from statistics import median
from typing import Any
from urllib.parse import urlparse

from ai_core.runtime.evidence.canonical_schema_normalizer import CanonicalSchemaNormalizer, SourceInvestigationReporter


_NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
_MEASURE_RE = re.compile(r"[-+]?\d+(?:\.\d+)?\s*(?:°\s*[A-Za-z]?|%|mm|cm|km/h|mph|m/s|hPa|kPa|¥|\$|€)", re.I)


@dataclass
class ConsensusPolicy:
    """Generic convergence policy for external evidence.

    No domain vocabulary is used here. The policy only evaluates source
    diversity, runtime-target alignment, measurement density, and numeric
    agreement across independent origins.
    """

    minimum_sources: int = 3
    minimum_aligned_sources: int = 2
    minimum_fact_count: int = 3
    minimum_score: float = 0.72
    outlier_z: float = 2.5


class EvidenceConsensusFusion:
    """Fuse independently materialized evidence into compact final material.

    The class deliberately avoids task-specific keywords. It treats every
    source as a set of structured observations, scores each source by generic
    quality signals, removes numeric outliers per target/unit bucket, and emits
    the compact material that the final model may read.
    """

    def fuse(
        self,
        *,
        documents: list[dict[str, Any]],
        known: dict[str, Any] | None,
        policy: ConsensusPolicy | None = None,
    ) -> dict[str, Any]:
        policy = policy or ConsensusPolicy()
        known = known if isinstance(known, dict) else {}
        canonical_normalizer = CanonicalSchemaNormalizer()
        source_packets = [self._source_packet(doc, known) for doc in documents if isinstance(doc, dict)]
        source_packets = [p for p in source_packets if p.get("url") or p.get("facts") or p.get("material")]

        all_facts: list[dict[str, Any]] = []
        for packet in source_packets:
            for fact in packet.get("facts", []):
                if isinstance(fact, dict):
                    fact = dict(fact)
                    fact.setdefault("source_url", packet.get("url", ""))
                    fact.setdefault("source_host", packet.get("host", ""))
                    fact.setdefault("source_score", packet.get("score", 0.0))
                    all_facts.append(fact)

        canonical_facts = canonical_normalizer.normalize_facts(all_facts)
        aligned_facts = [f for f in canonical_facts if self._is_aligned_fact(f, known)]
        measured_facts = [f for f in aligned_facts if self._has_measurement(f)]
        filtered_facts, outliers = self._remove_outliers(measured_facts, policy)
        source_count = len({p.get("host") or p.get("url") for p in source_packets if p.get("host") or p.get("url")})
        aligned_source_count = len({self._source_key(f) for f in filtered_facts if self._source_key(f)})
        field_coverage = self._coverage_score(filtered_facts, known)
        agreement_score = self._agreement_score(filtered_facts)
        structure_score = self._structure_score(source_packets, filtered_facts)
        score = round(min(1.0, 0.28 * field_coverage + 0.32 * agreement_score + 0.24 * structure_score + 0.16 * min(aligned_source_count / max(1, policy.minimum_sources), 1.0)), 3)
        passed = (
            source_count >= policy.minimum_sources
            and aligned_source_count >= policy.minimum_aligned_sources
            and len(filtered_facts) >= policy.minimum_fact_count
            and score >= policy.minimum_score
        )
        material = self._build_material(filtered_facts, source_packets, known)
        investigation_report = SourceInvestigationReporter().build(self._source_summaries(source_packets), consensus={"passed": passed, "quality": {"reason": "multi_source_convergence_not_available" if not passed else "multi_source_convergence_passed"}})
        if not material and filtered_facts:
            material = self._fallback_material(filtered_facts)
        return {
            "status": "passed" if passed else "insufficient",
            "passed": passed,
            "score": score,
            "source_count": source_count,
            "aligned_source_count": aligned_source_count,
            "fact_count": len(filtered_facts),
            "raw_fact_count": len(all_facts),
            "field_coverage": round(field_coverage, 3),
            "agreement_score": round(agreement_score, 3),
            "structure_score": round(structure_score, 3),
            "facts": filtered_facts,
            "outliers": outliers,
            "answer_material": material,
            "source_summaries": self._source_summaries(source_packets),
            "investigation_report": investigation_report,
            "quality": {
                "passed": passed,
                "score": score,
                "source_count": source_count,
                "aligned_source_count": aligned_source_count,
                "fact_count": len(filtered_facts),
                "field_coverage": round(field_coverage, 3),
                "agreement_score": round(agreement_score, 3),
                "structure_score": round(structure_score, 3),
                "outlier_count": len(outliers),
                "raw_evidence_omitted": True,
                "domain_specific_rules_used": False,
                "minimum_sources": policy.minimum_sources,
            },
        }

    def _source_packet(self, item: dict[str, Any], known: dict[str, Any]) -> dict[str, Any]:
        document = item.get("document") if isinstance(item.get("document"), dict) else item
        url = str(document.get("url") or item.get("url") or "")
        host = urlparse(url).netloc.lower()
        facts = document.get("normalized_facts") if isinstance(document.get("normalized_facts"), list) else []
        material = str(document.get("answer_material") or document.get("text_excerpt") or document.get("visible_text_excerpt") or "")
        quality = document.get("answer_material_quality") if isinstance(document.get("answer_material_quality"), dict) else {}
        structure_layers = document.get("extraction_layers") if isinstance(document.get("extraction_layers"), list) else []
        score = float(quality.get("score") or 0.0)
        score += 0.12 if facts else 0.0
        score += min(len(facts), 10) * 0.01
        score += 0.08 if structure_layers else 0.0
        score += self._text_alignment(material, known) * 0.1
        return {
            "url": url,
            "host": host,
            "title": document.get("title") or item.get("title") or "",
            "facts": [f for f in facts if isinstance(f, dict)],
            "material": material,
            "quality": quality,
            "layers": structure_layers,
            "score": round(min(1.0, score), 3),
        }

    def _is_aligned_fact(self, fact: dict[str, Any], known: dict[str, Any]) -> bool:
        if not known:
            return True
        text = " ".join(str(fact.get(k, "")) for k in ("target", "label", "context", "value", "unit")).casefold()
        values = self._known_values(known)
        if not values:
            return True
        # Require at least one runtime value or a non-empty target. This is
        # generic: it works for any task where the parser has normalized values.
        if fact.get("target"):
            return True
        return any(v in text for v in values if len(v) >= 2)

    def _known_values(self, known: dict[str, Any]) -> list[str]:
        values: list[str] = []
        for value in known.values():
            if isinstance(value, (list, tuple, set)):
                values.extend(str(x).casefold().strip() for x in value)
            elif isinstance(value, dict):
                values.extend(str(x).casefold().strip() for x in value.values())
            else:
                values.append(str(value).casefold().strip())
        return [v for v in values if v and v not in {"none", "null"}]

    def _has_measurement(self, fact: dict[str, Any]) -> bool:
        probe = " ".join(str(fact.get(k, "")) for k in ("value", "unit", "context"))
        return bool(_MEASURE_RE.search(probe))

    def _remove_outliers(self, facts: list[dict[str, Any]], policy: ConsensusPolicy) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for fact in facts:
            key = str(fact.get("canonical_key") or "|".join(str(fact.get(k, "")).casefold() for k in ("target", "unit")))
            buckets[key].append(fact)
        kept: list[dict[str, Any]] = []
        outliers: list[dict[str, Any]] = []
        for group in buckets.values():
            nums = [self._number(g) for g in group]
            nums = [n for n in nums if n is not None]
            if len(nums) < 4:
                kept.extend(group)
                continue
            mid = median(nums)
            deviations = [abs(n - mid) for n in nums]
            mad = median(deviations) or 1.0
            for fact in group:
                n = self._number(fact)
                if n is None:
                    kept.append(fact)
                    continue
                robust_z = 0.6745 * abs(n - mid) / mad
                if robust_z > policy.outlier_z:
                    rejected = dict(fact)
                    rejected["outlier_reason"] = "numeric_distance_from_group_median"
                    outliers.append(rejected)
                else:
                    kept.append(fact)
        return kept, outliers

    def _number(self, fact: dict[str, Any]) -> float | None:
        match = _NUMBER_RE.search(str(fact.get("value") or fact.get("context") or ""))
        if not match:
            return None
        try:
            return float(match.group(0))
        except Exception:
            return None

    def _source_key(self, fact: dict[str, Any]) -> str:
        return str(fact.get("source_host") or urlparse(str(fact.get("source_url") or "")).netloc.lower())

    def _coverage_score(self, facts: list[dict[str, Any]], known: dict[str, Any]) -> float:
        values = self._known_values(known)
        values = [v for v in values if len(v) >= 2]
        if not values:
            return 1.0 if facts else 0.0
        text = "\n".join(" ".join(str(f.get(k, "")) for k in ("target", "context", "label", "value")) for f in facts).casefold()
        matched = sum(1 for v in values if v in text)
        return matched / max(1, len(values))

    def _agreement_score(self, facts: list[dict[str, Any]]) -> float:
        if not facts:
            return 0.0
        buckets: dict[str, list[float]] = defaultdict(list)
        for fact in facts:
            n = self._number(fact)
            if n is None:
                continue
            key = str(fact.get("canonical_key") or "|".join(str(fact.get(k, "")).casefold() for k in ("target", "unit")))
            buckets[key].append(n)
        if not buckets:
            return min(1.0, len(facts) / 6)
        scores: list[float] = []
        for values in buckets.values():
            if len(values) == 1:
                scores.append(0.55)
                continue
            mid = median(values)
            spread = median([abs(v - mid) for v in values])
            scale = max(abs(mid), 1.0)
            scores.append(max(0.0, 1.0 - min(1.0, spread / scale)))
        return sum(scores) / len(scores)

    def _structure_score(self, packets: list[dict[str, Any]], facts: list[dict[str, Any]]) -> float:
        if not packets:
            return 0.0
        layer_score = 0.0
        for packet in packets:
            layers = packet.get("layers") if isinstance(packet.get("layers"), list) else []
            if layers:
                layer_score += 0.7
            if packet.get("facts"):
                layer_score += 0.3
        return min(1.0, (layer_score / max(1, len(packets))) + min(len(facts), 12) * 0.02)

    def _text_alignment(self, text: str, known: dict[str, Any]) -> float:
        values = self._known_values(known)
        if not values:
            return 0.0
        hay = str(text or "").casefold()
        return sum(1 for v in values if len(v) >= 2 and v in hay) / max(1, len(values))

    def _build_material(self, facts: list[dict[str, Any]], packets: list[dict[str, Any]], known: dict[str, Any]) -> str:
        ranked = sorted(facts, key=lambda f: (1 if f.get("target") else 0, float(f.get("source_score") or 0), float(f.get("confidence") or 0)), reverse=True)
        lines: list[str] = []
        seen: set[str] = set()
        for fact in ranked[:36]:
            target = str(fact.get("target") or "").strip()
            label = str(fact.get("canonical_label_signature") or fact.get("label") or fact.get("kind") or "measurement").strip()
            value = str(fact.get("value") or "").strip()
            unit = str(fact.get("unit") or "").strip()
            source = self._source_key(fact)
            context = " ".join(str(fact.get("context") or "").split())[:180]
            line = " | ".join(x for x in [target, label, (value + unit).strip(), source, context] if x)
            if line and line.casefold() not in seen:
                seen.add(line.casefold())
                lines.append(line)
        return "\n".join(lines[:32])

    def _fallback_material(self, facts: list[dict[str, Any]]) -> str:
        lines = []
        for fact in facts[:24]:
            probe = " ".join(str(fact.get(k, "")) for k in ("target", "label", "value", "unit", "context"))
            if _MEASURE_RE.search(probe):
                lines.append(" ".join(probe.split())[:240])
        return "\n".join(lines)

    def _source_summaries(self, packets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "url": p.get("url", ""),
                "host": p.get("host", ""),
                "title": p.get("title", ""),
                "score": p.get("score", 0.0),
                "fact_count": len(p.get("facts") or []),
                "layers": p.get("layers") or [],
            }
            for p in packets
        ]
