from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class EvidenceClaim:
    value: str
    normalized: tuple[int, ...]
    status: str
    source_url: str
    source_rank: int
    context: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["normalized"] = list(self.normalized)
        return data


class EvidenceClaimRanker:
    """Extract and rank generic evidence claims.

    This component is intentionally domain-neutral.  It does not know product,
    library, database, vendor, or business names.  It only applies generic
    rules that are useful for freshness-sensitive answers:

    - extract comparable dotted numeric identifiers from evidence text;
    - prefer source-backed evidence over generated answer text;
    - prefer stronger source hints when no runtime contract says otherwise;
    - prefer non-pre-release status over pre-release status;
    - detect when a draft answer mentions an older comparable identifier than
      the best evidence-backed identifier.
    """

    VERSION_PATTERN = re.compile(r"(?<![A-Za-z0-9])v?(\d+(?:\.\d+){0,3})(?![A-Za-z0-9])", re.IGNORECASE)
    STATUS_PATTERN = re.compile(
        r"\b(stable|current|latest|general\s+availability|ga|release|released|production|"
        r"beta|alpha|preview|rc|candidate|development|devel|snapshot|nightly|deprecated|legacy)\b",
        re.IGNORECASE,
    )
    NEGATIVE_STATUS = {"beta", "alpha", "preview", "rc", "candidate", "development", "devel", "snapshot", "nightly"}
    POSITIVE_STATUS = {"stable", "current", "latest", "general availability", "ga", "release", "released", "production"}
    LOW_VALUE_CONTEXT = re.compile(r"\b(status|http|error|port|height|width|css|px|ms|kb|mb|gb)\b", re.IGNORECASE)

    def extract_from_materials(self, materials: list[dict[str, Any]]) -> list[dict[str, Any]]:
        claims: list[EvidenceClaim] = []
        for material in materials:
            for text, url, source_hint in self._text_carriers(material):
                claims.extend(self._claims_from_text(text=text, source_url=url, source_hint=source_hint))
        return [claim.to_dict() for claim in self._dedupe_and_sort(claims)]

    def best_claim(self, claims: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not claims:
            return None
        sorted_claims = self._sort_dict_claims(claims)
        return sorted_claims[0] if sorted_claims else None

    def answer_consistent(self, answer: str, claims: list[dict[str, Any]]) -> dict[str, Any]:
        best = self.best_claim(claims)
        answer_versions = [self._normalize_version(m.group(1)) for m in self.VERSION_PATTERN.finditer(str(answer or ""))]
        answer_versions = [v for v in answer_versions if v]
        if not best or not answer_versions:
            return {
                "passed": True,
                "reason": "no_comparable_claim_or_answer_identifier",
                "best_claim": best,
                "answer_identifiers": [list(v) for v in answer_versions],
            }
        best_version = tuple(int(x) for x in best.get("normalized") or [])
        if not best_version:
            return {
                "passed": True,
                "reason": "best_claim_not_comparable",
                "best_claim": best,
                "answer_identifiers": [list(v) for v in answer_versions],
            }
        max_answer = max(answer_versions)
        passed = max_answer >= best_version
        return {
            "passed": passed,
            "reason": "answer_matches_best_evidence" if passed else "answer_older_than_best_evidence",
            "best_claim": best,
            "answer_identifiers": [list(v) for v in answer_versions],
        }

    def filter_verified_facts(self, facts: list[dict[str, Any]], claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Keep facts aligned with the strongest comparable claim when available."""
        best = self.best_claim(claims)
        if not best:
            return facts
        best_value = str(best.get("value") or "")
        if not best_value:
            return facts
        selected: list[dict[str, Any]] = []
        for fact in facts:
            text = " ".join(str(fact.get(k) or "") for k in ("value", "context", "label"))
            if best_value in text:
                selected.append(fact)
        return selected or facts

    def _claims_from_text(self, *, text: str, source_url: str, source_hint: str) -> list[EvidenceClaim]:
        compact = " ".join(str(text or "").split())
        if not compact:
            return []
        claims: list[EvidenceClaim] = []
        for match in self.VERSION_PATTERN.finditer(compact):
            raw = match.group(1)
            normalized = self._normalize_version(raw)
            if not normalized:
                continue
            context = compact[max(0, match.start() - 160): min(len(compact), match.end() + 220)]
            if self._looks_low_value(context=context, normalized=normalized):
                continue
            status = self._status(context)
            confidence = self._confidence(context=context, source_url=source_url, source_hint=source_hint, status=status)
            claims.append(EvidenceClaim(
                value=raw,
                normalized=normalized,
                status=status,
                source_url=source_url,
                source_rank=self._source_rank(source_url=source_url, source_hint=source_hint),
                context=context[:520],
                confidence=confidence,
            ))
        return claims

    def _text_carriers(self, material: Any) -> list[tuple[str, str, str]]:
        carriers: list[tuple[str, str, str]] = []

        def walk(value: Any, inherited_url: str = "", source_hint: str = "") -> None:
            if len(carriers) >= 80:
                return
            if isinstance(value, dict):
                url = inherited_url
                for key in ("source_url", "url", "href", "official_documentation_url", "evidence_url"):
                    item = value.get(key)
                    if isinstance(item, str) and item.startswith(("http://", "https://")):
                        url = item
                        break
                hint = source_hint or str(value.get("source") or value.get("provider") or value.get("source_level") or "")
                for key in (
                    "text", "text_excerpt", "visible_text_excerpt", "dom_evidence_text",
                    "snippet", "summary", "title", "answer", "final_answer", "generated_content",
                    "content", "value", "context",
                ):
                    item = value.get(key)
                    if isinstance(item, str) and item.strip():
                        carriers.append((item, url, hint))
                for item in value.values():
                    if isinstance(item, (dict, list)):
                        walk(item, url, hint)
            elif isinstance(value, list):
                for item in value[:80]:
                    walk(item, inherited_url, source_hint)
            elif isinstance(value, str) and value.strip():
                carriers.append((value, inherited_url, source_hint))

        walk(material)
        return carriers

    def _normalize_version(self, value: str) -> tuple[int, ...]:
        try:
            parts = tuple(int(part) for part in str(value).split(".") if part != "")
        except Exception:
            return tuple()
        if not parts:
            return tuple()
        # Reject very long year-like identifiers when there is no dotted detail.
        if len(parts) == 1 and parts[0] >= 1900:
            return tuple()
        return parts

    def _status(self, context: str) -> str:
        statuses = [m.group(1).casefold().replace("  ", " ") for m in self.STATUS_PATTERN.finditer(context or "")]
        if not statuses:
            return "unspecified"
        if any(s in self.NEGATIVE_STATUS for s in statuses):
            if any(s in self.POSITIVE_STATUS for s in statuses):
                return "mixed"
            return "pre_release"
        if any(s in self.POSITIVE_STATUS for s in statuses):
            return "release"
        return "unspecified"

    def _source_rank(self, *, source_url: str, source_hint: str) -> int:
        hint = str(source_hint or "").casefold()
        if "runtime_native" in hint:
            return 5
        if "structured" in hint:
            return 4
        if "verified" in hint:
            return 3
        host = urlparse(source_url or "").netloc.casefold()
        if not host:
            return 0
        labels = [p for p in host.split(".") if p]
        if len(labels) <= 2:
            return 3
        if labels[0] in {"www", "docs", "developer", "dev", "learn", "support", "help", "releases", "download"}:
            return 3
        return 2

    def _confidence(self, *, context: str, source_url: str, source_hint: str, status: str) -> float:
        score = 0.45
        score += min(self._source_rank(source_url=source_url, source_hint=source_hint), 5) * 0.08
        if status == "release":
            score += 0.18
        elif status == "mixed":
            score += 0.04
        elif status == "pre_release":
            score -= 0.16
        if re.search(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b", context or ""):
            score += 0.05
        return max(0.0, min(score, 0.98))

    def _looks_low_value(self, *, context: str, normalized: tuple[int, ...]) -> bool:
        if not normalized:
            return True
        if len(normalized) == 1 and normalized[0] <= 9 and not self.STATUS_PATTERN.search(context or ""):
            return True
        if self.LOW_VALUE_CONTEXT.search(context or "") and not self.STATUS_PATTERN.search(context or ""):
            return True
        return False

    def _dedupe_and_sort(self, claims: list[EvidenceClaim]) -> list[EvidenceClaim]:
        best: dict[tuple[tuple[int, ...], str, str], EvidenceClaim] = {}
        for claim in claims:
            key = (claim.normalized, claim.status, claim.source_url)
            current = best.get(key)
            if current is None or self._claim_sort_key(claim) > self._claim_sort_key(current):
                best[key] = claim
        return sorted(best.values(), key=self._claim_sort_key, reverse=True)[:24]

    def _sort_dict_claims(self, claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
        def key(item: dict[str, Any]) -> tuple[int, int, tuple[int, ...], float]:
            status = str(item.get("status") or "unspecified")
            status_rank = {"release": 3, "mixed": 2, "unspecified": 1, "pre_release": 0}.get(status, 1)
            normalized = tuple(int(x) for x in (item.get("normalized") or []) if isinstance(x, int))
            return (status_rank, int(item.get("source_rank") or 0), normalized, float(item.get("confidence") or 0.0))
        return sorted([c for c in claims if isinstance(c, dict)], key=key, reverse=True)

    def _claim_sort_key(self, claim: EvidenceClaim) -> tuple[int, int, tuple[int, ...], float]:
        status_rank = {"release": 3, "mixed": 2, "unspecified": 1, "pre_release": 0}.get(claim.status, 1)
        return (status_rank, claim.source_rank, claim.normalized, claim.confidence)
