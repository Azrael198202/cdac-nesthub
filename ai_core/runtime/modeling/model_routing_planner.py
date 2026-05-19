from __future__ import annotations

from typing import Any

from ai_core.runtime.modeling.capability_topology import RuntimeModelTopology
from ai_core.runtime.modeling.complexity_estimator import ComplexityEstimator
from ai_core.runtime.modeling.feedback_escalator import FeedbackEscalator


class ModelRoutingPlanner:
    """Plans provider routes for cognitive runtime nodes.

    The planner is generic and provider-neutral.  Runtime configuration maps
    route names to providers; this class only selects a route name from
    structural complexity and feedback signals.
    """

    def __init__(self) -> None:
        self.topology_loader = RuntimeModelTopology()
        self.complexity = ComplexityEstimator()
        self.feedback = FeedbackEscalator()

    def plan(
        self,
        *,
        node_id: str,
        adapter: dict[str, Any],
        prompt: dict[str, Any] | None,
        rendered_user_prompt: str,
        schema: dict[str, Any] | None,
        provider_config: dict[str, Any],
        default_route: list[str],
    ) -> dict[str, Any]:
        topology = self.topology_loader.load()
        feedback = self.feedback.feedback_for(node_id=node_id, adapter=adapter)
        complexity = self.complexity.estimate(
            node_id=node_id,
            adapter=adapter,
            prompt=prompt,
            rendered_user_prompt=rendered_user_prompt,
            schema=schema,
            feedback=feedback,
            topology=topology,
        )
        routes = provider_config.get("routes") if isinstance(provider_config.get("routes"), dict) else {}
        route_name = self._select_route_name(node_id=node_id, adapter=adapter, complexity=complexity, topology=topology)
        escalated = False
        if self.feedback.should_escalate(node_id=node_id, adapter=adapter, complexity=complexity, topology=topology):
            node_policy = self._node_policy(node_id=node_id, topology=topology)
            route_name = str(node_policy.get("escalate_route_name") or "strong_reasoning")
            escalated = True
        route = routes.get(route_name) if isinstance(routes.get(route_name), list) else None
        if not route:
            route = default_route
            route_name = "adapter_or_default"
        return {
            "route": [str(x) for x in route if str(x).strip()],
            "route_name": route_name,
            "complexity": complexity,
            "escalated": escalated,
            "feedback": feedback,
        }

    def _select_route_name(self, *, node_id: str, adapter: dict[str, Any], complexity: dict[str, Any], topology: dict[str, Any]) -> str:
        explicit = adapter.get("route_name") or adapter.get("model_route_name")
        if isinstance(explicit, str) and explicit.strip():
            return explicit.strip()
        node_policy = self._node_policy(node_id=node_id, topology=topology)
        level = str(complexity.get("level") or "medium")
        if level in {"high", "critical"} and node_policy.get("escalate_route_name"):
            return str(node_policy["escalate_route_name"])
        if node_policy.get("route_name"):
            return str(node_policy["route_name"])
        complexity_routes = topology.get("complexity_routes") if isinstance(topology.get("complexity_routes"), dict) else {}
        return str(complexity_routes.get(level) or "local_capable")

    def _node_policy(self, *, node_id: str, topology: dict[str, Any]) -> dict[str, Any]:
        nodes = topology.get("nodes") if isinstance(topology.get("nodes"), dict) else {}
        value = nodes.get(str(node_id or ""))
        return value if isinstance(value, dict) else {}
