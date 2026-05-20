from __future__ import annotations

import math
import re
from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class EvidenceBudget:
    """Adaptive evidence budget.

    This is not a hard quality cap. It is a governance contract that decides how
    much raw material may be fetched and how much compact material may be passed
    forward after local ranking, deduplication and compression. The rules are
    domain-neutral and use only runtime variables, source diversity, structural
    density and observed quality.
    """

    candidate_window: int = 6
    min_sources: int = 3
    max_sources: int = 5
    initial_fetches: int = 2
    incremental_fetches: int = 1
    max_fetches: int = 5
    fetch_chars_per_source: int = 18000
    llm_material_chars: int = 6000
    fact_limit: int = 48
    block_limit: int = 32
    stop_quality_score: float = 0.78
    stop_min_fact_count: int = 4

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EvidenceBudgetAllocator:
    """Build evidence budgets from task complexity without business terms."""

    def allocate(
        self,
        *,
        known: dict[str, Any] | None = None,
        objective: str = "",
        candidates: list[dict[str, Any]] | None = None,
        policy: dict[str, Any] | None = None,
    ) -> EvidenceBudget:
        known = known if isinstance(known, dict) else {}
        candidates = candidates if isinstance(candidates, list) else []
        policy = policy if isinstance(policy, dict) else {}
        variable_count = self._variable_count(known)
        objective_len = len(str(objective or ""))
        source_count = len(candidates)

        complexity = 0
        complexity += min(variable_count, 6)
        complexity += 1 if objective_len > 80 else 0
        complexity += 1 if objective_len > 180 else 0
        complexity += 1 if source_count > 4 else 0

        max_sources = self._configured_int(policy, "adaptive_max_sources", 5)
        min_sources = self._configured_int(policy, "adaptive_min_sources", 3)
        fetch_chars = self._configured_int(policy, "fetch_chars_per_source", 18000)
        llm_chars = self._configured_int(policy, "llm_material_chars", 6000)

        # More variables need more cross-source evidence, but the budget grows
        # gradually and can stop early when quality is sufficient.
        desired_sources = min(max_sources, max(min_sources, 3 + math.ceil(max(0, complexity - 2) / 2)))
        return EvidenceBudget(
            candidate_window=max(desired_sources + 1, self._configured_int(policy, "candidate_window", 6)),
            min_sources=min_sources,
            max_sources=max_sources,
            initial_fetches=min(desired_sources, self._configured_int(policy, "initial_fetches", 2)),
            incremental_fetches=max(1, self._configured_int(policy, "incremental_fetches", 1)),
            max_fetches=max(desired_sources, self._configured_int(policy, "max_fetches", max_sources)),
            fetch_chars_per_source=max(4000, fetch_chars),
            llm_material_chars=max(1200, llm_chars),
            fact_limit=max(12, self._configured_int(policy, "fact_limit", 48)),
            block_limit=max(8, self._configured_int(policy, "block_limit", 32)),
            stop_quality_score=float(policy.get("stop_quality_score", 0.78)),
            stop_min_fact_count=max(1, self._configured_int(policy, "stop_min_fact_count", 4)),
        )

    def should_stop(self, *, normalized: dict[str, Any], fetched_count: int, budget: EvidenceBudget) -> bool:
        quality = normalized.get("answer_material_quality") if isinstance(normalized, dict) else {}
        facts = normalized.get("normalized_facts") if isinstance(normalized, dict) else []
        if not isinstance(quality, dict):
            quality = {}
        if not isinstance(facts, list):
            facts = []
        score = float(quality.get("score") or 0.0)
        source_count = int(quality.get("source_count") or quality.get("aligned_source_count") or 0)
        if (
            quality.get("passed")
            and score >= budget.stop_quality_score
            and len(facts) >= budget.stop_min_fact_count
            and source_count >= budget.min_sources
        ):
            return True
        return fetched_count >= budget.max_fetches

    def _variable_count(self, known: dict[str, Any]) -> int:
        count = 0
        for value in known.values():
            if isinstance(value, (list, tuple, set)):
                count += len([x for x in value if str(x).strip()])
            elif isinstance(value, dict):
                count += len([x for x in value.values() if str(x).strip()])
            elif str(value).strip():
                count += 1
        return count

    def _configured_int(self, policy: dict[str, Any], key: str, default: int) -> int:
        try:
            return int(policy.get(key, default))
        except Exception:
            return default


class CandidateEvidenceRanker:
    """Rank and diversify candidate sources before fetching.

    Uses no domain vocabulary. It scores parameter overlap, source score,
    snippet density, URL diversity and visible structural signals.
    """

    VALUE_PATTERN = re.compile(r"[-+]?\d+(?:\.\d+)?\s*(?:[^\s\d]{0,8})")

    def rank(self, *, candidates: list[dict[str, Any]], known: dict[str, Any], budget: EvidenceBudget) -> list[dict[str, Any]]:
        scored: list[tuple[float, str, dict[str, Any]]] = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            url = self._url(candidate)
            text = self._candidate_text(candidate)
            score = float(candidate.get("score") or candidate.get("candidate_score") or 0)
            score += self._known_overlap(text, known) * 100
            score += min(len(self.VALUE_PATTERN.findall(text)), 12) * 1.5
            if url:
                score += 5
            scored.append((score, self._host(url), candidate))
        scored.sort(key=lambda x: x[0], reverse=True)

        selected: list[dict[str, Any]] = []
        host_counts: dict[str, int] = {}
        for _, host, candidate in scored:
            if len(selected) >= budget.candidate_window:
                break
            if host and host_counts.get(host, 0) >= 1 and len(selected) < budget.min_sources:
                continue
            host_counts[host] = host_counts.get(host, 0) + 1
            selected.append(candidate)
        if len(selected) < min(len(scored), budget.candidate_window):
            for _, _, candidate in scored:
                if candidate not in selected:
                    selected.append(candidate)
                if len(selected) >= budget.candidate_window:
                    break
        return selected

    def _known_overlap(self, text: str, known: dict[str, Any]) -> float:
        hay = str(text or "").casefold()
        values = []
        for value in known.values():
            if isinstance(value, (list, tuple, set)):
                values.extend([str(x) for x in value])
            elif isinstance(value, dict):
                values.extend([str(x) for x in value.values()])
            else:
                values.append(str(value))
        values = [v.casefold().strip() for v in values if len(v.strip()) >= 2]
        if not values:
            return 0.2
        matched = sum(1 for value in values if value in hay)
        return matched / max(1, len(values))

    def _candidate_text(self, candidate: dict[str, Any]) -> str:
        parts: list[str] = []
        for key in ("name", "title", "snippet", "url", "official_documentation_url"):
            value = candidate.get(key)
            if isinstance(value, str):
                parts.append(value)
        evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
        for key in ("text_excerpt", "visible_text_excerpt", "snippet", "title"):
            value = evidence.get(key)
            if isinstance(value, str):
                parts.append(value)
        return "\n".join(parts)

    def _url(self, candidate: dict[str, Any]) -> str:
        for key in ("url", "official_documentation_url"):
            value = candidate.get(key)
            if isinstance(value, str):
                return value
        evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
        for key in ("url", "official_documentation_url"):
            value = evidence.get(key)
            if isinstance(value, str):
                return value
        return ""

    def _host(self, url: str) -> str:
        match = re.match(r"https?://([^/]+)", str(url or ""), flags=re.I)
        return match.group(1).lower() if match else ""
