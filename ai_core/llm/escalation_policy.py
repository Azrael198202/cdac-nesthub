from __future__ import annotations

from typing import Any


class ModelEscalationPolicy:
    """
    Config-driven escalation policy.

    IMPORTANT:
    This class must not contain business keywords, domain words,
    language-specific task words, or semantic parsing logic.

    It only evaluates generic runtime signals. Business-specific escalation
    rules should be generated into runtime config and passed as structured data.

    Example runtime signals:
      - requires_capability_generation
      - requires_tool_generation
      - requires_code_generation
      - requires_browser_blueprint
      - repeated_failures
      - low_confidence
      - policy_requires_strong_model
    """

    DEFAULT_STRONG_ROUTE = ["openai"]

    def should_escalate(
        self,
        *,
        user_input: str = "",
        node_id: str | None = None,
        reason: str | None = None,
        required_capability: str | None = None,
        signals: dict[str, Any] | None = None,
        policy: dict[str, Any] | None = None,
    ) -> bool:
        signals = signals or {}
        policy = policy or {}

        if bool(policy.get("force_escalation")):
            return True

        if node_id in set(policy.get("strong_model_nodes", [])):
            return True

        signal_names = set(policy.get("escalation_signals", [
            "requires_capability_generation",
            "requires_tool_generation",
            "requires_code_generation",
            "requires_blueprint_generation",
            "requires_browser_blueprint",
            "requires_schema_design",
            "requires_workflow_design",
            "repeated_failures",
            "low_confidence",
            "policy_requires_strong_model",
        ]))

        for name in signal_names:
            if bool(signals.get(name)):
                return True

        min_confidence = policy.get("min_confidence")
        confidence = signals.get("confidence")
        if isinstance(min_confidence, (int, float)) and isinstance(confidence, (int, float)):
            if confidence < min_confidence:
                return True

        failure_count = signals.get("failure_count")
        max_local_failures = policy.get("max_local_failures")
        if isinstance(failure_count, int) and isinstance(max_local_failures, int):
            if failure_count >= max_local_failures:
                return True

        return False

    def preferred_route(
        self,
        default_route: list[str],
        strong_route: list[str] | None = None,
        policy: dict[str, Any] | None = None,
    ) -> list[str]:
        policy = policy or {}
        if strong_route:
            return strong_route
        configured = policy.get("strong_route")
        if isinstance(configured, list) and configured:
            return configured
        return self.DEFAULT_STRONG_ROUTE + [x for x in default_route if x not in self.DEFAULT_STRONG_ROUTE]
