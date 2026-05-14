from __future__ import annotations

from typing import Any

from ai_core.utils.safe_json import make_json_safe


class CandidateResultSynthesizer:
    """Select or synthesize the best result from multiple candidate attempts.

    Domain-neutral scoring: prefer successful, high-quality evidence with high
    candidate score, live retrieval, and low error risk. The synthesizer does not
    know provider names or business-specific fields.
    """

    def choose(self, attempts: list[dict[str, Any]]) -> dict[str, Any] | None:
        successful = [a for a in attempts if isinstance(a, dict) and a.get("status") == "success"]
        if not successful:
            return None
        ranked = sorted(successful, key=self._attempt_score, reverse=True)
        best = ranked[0]
        result = best.get("result") if isinstance(best.get("result"), dict) else {}
        result.setdefault("fallback", {})["parallel_candidate_evaluation"] = {
            "selected_attempt_index": best.get("attempt_index"),
            "evaluated_attempts": len(attempts),
            "successful_attempts": len(successful),
            "selection_score": round(self._attempt_score(best), 3),
            "top_candidates": [self._compact(a) for a in ranked[:3]],
        }
        return {"status": "success", "tool": best.get("installed_tool"), "result": result, "attempts": attempts}

    def _attempt_score(self, attempt: dict[str, Any]) -> float:
        candidate = attempt.get("candidate") if isinstance(attempt.get("candidate"), dict) else {}
        result = attempt.get("result") if isinstance(attempt.get("result"), dict) else {}
        score = float(candidate.get("score") or 0)
        quality = (result.get("quality") or {}).get("evidence") if isinstance(result.get("quality"), dict) else None
        if not isinstance(quality, dict):
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            quality = data.get("answer_material_quality") if isinstance(data.get("answer_material_quality"), dict) else {}
        if quality.get("passed"):
            score += 100
        score += float(quality.get("score") or 0) * 50
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        retrieval = data.get("retrieval") if isinstance(data.get("retrieval"), dict) else {}
        if retrieval.get("used_live_fetch"):
            score += 20
        if result.get("source"):
            score += 5
        return score

    def _compact(self, attempt: dict[str, Any]) -> dict[str, Any]:
        candidate = attempt.get("candidate") if isinstance(attempt.get("candidate"), dict) else {}
        return make_json_safe({
            "attempt_index": attempt.get("attempt_index"),
            "score": round(self._attempt_score(attempt), 3),
            "candidate": {
                "name": candidate.get("name"),
                "url": candidate.get("url") or candidate.get("official_documentation_url"),
                "source": candidate.get("source"),
                "tool_type": candidate.get("tool_type"),
                "candidate_score": candidate.get("score"),
            },
        })
