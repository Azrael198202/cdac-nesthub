from __future__ import annotations

from typing import Any


class ComplexityEstimator:
    """Generic cognitive complexity estimator.

    This class deliberately avoids domain/business vocabulary.  It uses only
    structural signals: node role, prompt/schema size, requested generic model
    capabilities, prior failures, and runtime-provided policy hints.
    """

    DEFAULT_LEVELS = ("low", "medium", "high", "critical")

    def estimate(
        self,
        *,
        node_id: str,
        adapter: dict[str, Any],
        prompt: dict[str, Any] | None = None,
        rendered_user_prompt: str = "",
        schema: dict[str, Any] | None = None,
        feedback: dict[str, Any] | None = None,
        topology: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        topology = topology or {}
        feedback = feedback or {}
        node_id = str(node_id or "")
        adapter = adapter or {}
        prompt = prompt or {}
        schema = schema or {}

        explicit = adapter.get("complexity") or adapter.get("model_complexity")
        if isinstance(explicit, str) and explicit.strip():
            return {"level": self._normalize_level(explicit), "score": self._score_for_level(explicit), "reasons": ["adapter_explicit"]}

        score = 0
        reasons: list[str] = []

        node_policy = self._node_policy(node_id=node_id, topology=topology)
        base = node_policy.get("base_complexity")
        if isinstance(base, str) and base.strip():
            score += self._score_for_level(base)
            reasons.append("node_policy_base")
        else:
            score += 1
            reasons.append("default_low")

        text_len = len(str(rendered_user_prompt or ""))
        if text_len > int(topology.get("large_prompt_chars", 10000)):
            score += 2
            reasons.append("large_prompt")
        elif text_len > int(topology.get("medium_prompt_chars", 4000)):
            score += 1
            reasons.append("medium_prompt")

        schema_size = len(str(schema or {}))
        if schema_size > int(topology.get("large_schema_chars", 10000)):
            score += 2
            reasons.append("large_schema")
        elif schema_size > int(topology.get("medium_schema_chars", 4000)):
            score += 1
            reasons.append("medium_schema")

        requested = self._requested_capabilities(adapter)
        high_weighted = set(str(x) for x in topology.get("high_weight_capabilities", []) if str(x).strip())
        critical_weighted = set(str(x) for x in topology.get("critical_weight_capabilities", []) if str(x).strip())
        if requested & critical_weighted:
            score += 3
            reasons.append("critical_capability_requested")
        elif requested & high_weighted:
            score += 2
            reasons.append("high_capability_requested")

        failure_count = int(feedback.get("failure_count") or 0)
        dissatisfaction_count = int(feedback.get("dissatisfaction_count") or 0)
        if failure_count:
            score += min(3, failure_count)
            reasons.append("prior_failures")
        if dissatisfaction_count:
            score += min(3, dissatisfaction_count)
            reasons.append("prior_dissatisfaction")

        level = self._level_for_score(score)
        return {"level": level, "score": score, "reasons": reasons}

    def _requested_capabilities(self, adapter: dict[str, Any]) -> set[str]:
        values: list[Any] = []
        for key in ("required_model_capabilities", "model_capabilities", "preferred_capabilities"):
            item = adapter.get(key)
            if isinstance(item, list):
                values.extend(item)
        return {str(x) for x in values if str(x).strip()}

    def _node_policy(self, *, node_id: str, topology: dict[str, Any]) -> dict[str, Any]:
        nodes = topology.get("nodes") if isinstance(topology.get("nodes"), dict) else {}
        value = nodes.get(node_id)
        return value if isinstance(value, dict) else {}

    def _normalize_level(self, level: str) -> str:
        text = str(level or "").strip().lower()
        return text if text in self.DEFAULT_LEVELS else "medium"

    def _score_for_level(self, level: str) -> int:
        return {"low": 1, "medium": 3, "high": 5, "critical": 7}.get(self._normalize_level(level), 3)

    def _level_for_score(self, score: int) -> str:
        if score >= 8:
            return "critical"
        if score >= 5:
            return "high"
        if score >= 3:
            return "medium"
        return "low"
