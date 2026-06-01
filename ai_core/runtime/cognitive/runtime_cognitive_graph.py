from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_core.config.paths import CONFIGS_DIR, RUNTIME_GENERATED
from ai_core.runtime.cognitive.prompt_audit_store import PromptAuditStore


@dataclass(frozen=True)
class RuntimeNodeDecision:
    node_id: str
    role: str
    model_policy: str
    route_name: str
    escalate_route_name: str
    max_prompt_chars: int
    temperature: float
    json_only: bool


class RuntimeCognitiveGraph:
    """Small-model orchestration policy for the generic runtime brain.

    This class is a governance layer, not a capability implementation.  It maps
    cognitive stages to model routes, prompt budgets, audit requirements, and
    quality gates so the runtime can use fast local models for simple nodes and
    stronger routes only where the graph requires them.
    """

    def __init__(self, policy_path: Path | None = None) -> None:
        self.policy_path = policy_path
        self.audit = PromptAuditStore()

    def load_policy(self) -> dict[str, Any]:
        candidates = []
        if self.policy_path:
            candidates.append(self.policy_path)
        candidates.extend([
            RUNTIME_GENERATED / "system_topology" / "cognitive_runtime_graph.json",
            CONFIGS_DIR / "cognitive_runtime_graph.seed.json",
        ])
        for path in candidates:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(data, dict) and isinstance(data.get("nodes"), list):
                return data
        return self._default_policy()

    def decision_for(self, node_id: str) -> RuntimeNodeDecision:
        policy = self.load_policy()
        node = self._node(policy, node_id)
        model_policy_name = str(node.get("model_policy") or "small_semantic")
        model_policies = policy.get("model_policies") if isinstance(policy.get("model_policies"), dict) else {}
        model_policy = model_policies.get(model_policy_name) if isinstance(model_policies.get(model_policy_name), dict) else {}
        return RuntimeNodeDecision(
            node_id=str(node.get("id") or node_id or "general_runtime"),
            role=str(node.get("role") or "generic_runtime_node"),
            model_policy=model_policy_name,
            route_name=str(model_policy.get("route_name") or "local_balanced"),
            escalate_route_name=str(model_policy.get("escalate_route_name") or ""),
            max_prompt_chars=max(0, int(model_policy.get("max_prompt_chars") or 0)),
            temperature=float(model_policy.get("temperature") or 0),
            json_only=bool(model_policy.get("json_only", True)),
        )

    def compact_prompt(self, *, node_id: str, instruction: str, context: dict[str, Any] | None = None) -> str:
        decision = self.decision_for(node_id)
        context = context if isinstance(context, dict) else {}
        body = {
            "role": decision.role,
            "rules": [
                "Use only the provided instruction and context.",
                "Return the requested structure only.",
                "Do not invent execution results.",
            ],
            "instruction": str(instruction or ""),
            "context": self._slim_context(context),
        }
        prompt = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        if decision.max_prompt_chars and len(prompt) > decision.max_prompt_chars:
            prompt = prompt[: decision.max_prompt_chars]
        return prompt

    def audit_prompt(
        self,
        *,
        node_id: str,
        model: str | None,
        model_source: str | None,
        prompt: str,
        output_status: str | None = None,
        route_name: str | None = None,
    ) -> dict[str, Any]:
        decision = self.decision_for(node_id)
        return self.audit.append(
            stage_id=decision.node_id,
            node_id=node_id,
            model=model,
            model_source=model_source,
            prompt=prompt,
            output_status=output_status,
            route_name=route_name or decision.route_name,
            extra={"model_policy": decision.model_policy, "json_only": decision.json_only},
        )

    def graph_summary(self) -> dict[str, Any]:
        policy = self.load_policy()
        return {
            "version": policy.get("version"),
            "node_count": len(policy.get("nodes") or []),
            "nodes": [self.decision_for(str(n.get("id"))).__dict__ for n in policy.get("nodes", []) if isinstance(n, dict)],
            "quality_gates": policy.get("quality_gates") if isinstance(policy.get("quality_gates"), dict) else {},
        }

    def _node(self, policy: dict[str, Any], node_id: str) -> dict[str, Any]:
        for item in policy.get("nodes", []):
            if isinstance(item, dict) and str(item.get("id")) == str(node_id):
                return item
        return {"id": str(node_id or "general_runtime"), "role": "generic_runtime_node", "model_policy": "small_semantic"}

    def _slim_context(self, context: dict[str, Any]) -> dict[str, Any]:
        slim: dict[str, Any] = {}
        for key, value in list(context.items())[:24]:
            if isinstance(value, (str, int, float, bool)) or value is None:
                slim[str(key)] = value
            elif isinstance(value, list):
                slim[str(key)] = value[:8]
            elif isinstance(value, dict):
                slim[str(key)] = {str(k): v for k, v in list(value.items())[:12]}
            else:
                slim[str(key)] = str(value)[:200]
        return slim

    def _default_policy(self) -> dict[str, Any]:
        return {
            "version": "fallback",
            "nodes": [{"id": "general_runtime", "role": "generic_runtime_node", "model_policy": "small_semantic"}],
            "model_policies": {"small_semantic": {"route_name": "local_balanced", "max_prompt_chars": 1200, "temperature": 0, "json_only": True}},
            "quality_gates": {"json_nodes": [], "locked_plan_nodes": [], "trace_required": True},
        }
