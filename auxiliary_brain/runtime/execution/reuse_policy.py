from __future__ import annotations

from dataclasses import dataclass
from typing import Any


COMPILED_DIRECT = "compiled_direct"
DYNAMIC_REFRESH = "dynamic_refresh"
HYBRID = "hybrid"


@dataclass(frozen=True)
class ExecutionReusePolicyClassifier:
    """Classify task, step, and capability execution reuse from contracts only.

    The classifier is deliberately domain-neutral. It does not inspect task
    names, capability names, agent names, or business wording. It reads generic
    runtime contracts that already exist in the compiled graph:

    - source contracts that require fresh/source material
    - execution contracts that lock a refresh-capable method
    - explicit freshness/reuse declarations provided by generated artifacts
    - dependency/binding shape

    The output is durable policy metadata used by scheduled execution to decide
    whether a node may run as a compiled direct node or must be dynamically
    refreshed on each run.
    """

    dynamic_methods: tuple[str, ...] = (
        "web_search",
        "source_retrieval",
        "external_source_retrieval",
        "remote_query",
        "provider_query",
        "live_query",
    )

    def apply_to_task_graph(self, task_graph: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(task_graph, dict):
            return task_graph
        graph = dict(task_graph)
        tasks = graph.get("tasks") if isinstance(graph.get("tasks"), list) else []
        classified_tasks: list[dict[str, Any]] = []
        step_policies: list[dict[str, Any]] = []
        for index, item in enumerate(tasks, start=1):
            if not isinstance(item, dict):
                continue
            step_policy = self.classify_step(item, index=index)
            updated = dict(item)
            updated["execution_reuse_policy"] = step_policy
            classified_tasks.append(updated)
            step_policies.append(step_policy)
        graph["tasks"] = classified_tasks
        graph["execution_reuse_policy"] = self.classify_task(step_policies, graph)
        return graph

    def apply_to_compiled_step(self, step: dict[str, Any], *, index: int = 0) -> dict[str, Any]:
        if not isinstance(step, dict):
            return step
        updated = dict(step)
        updated["execution_reuse_policy"] = self.classify_step(updated, index=index)
        return updated

    def classify_task(self, step_policies: list[dict[str, Any]], task_graph: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized = [p for p in step_policies if isinstance(p, dict)]
        if not normalized:
            mode = COMPILED_DIRECT
        else:
            dynamic = [p for p in normalized if p.get("mode") == DYNAMIC_REFRESH]
            direct = [p for p in normalized if p.get("mode") == COMPILED_DIRECT]
            if dynamic and direct:
                mode = HYBRID
            elif dynamic:
                mode = DYNAMIC_REFRESH
            else:
                mode = COMPILED_DIRECT
        return {
            "mode": mode,
            "scope": "task",
            "policy_source": "compiled_contracts",
            "dynamic_step_ids": [str(p.get("step_id") or "") for p in normalized if p.get("mode") == DYNAMIC_REFRESH and str(p.get("step_id") or "")],
            "compiled_step_ids": [str(p.get("step_id") or "") for p in normalized if p.get("mode") == COMPILED_DIRECT and str(p.get("step_id") or "")],
            "verification_policy": "lightweight_structural" if mode == COMPILED_DIRECT else "runtime_result_verification",
            "planning_policy": "do_not_replan_on_scheduled_run" if mode in {COMPILED_DIRECT, HYBRID, DYNAMIC_REFRESH} else "default",
            "llm_policy": "avoid_for_compiled_direct_nodes" if mode in {COMPILED_DIRECT, HYBRID} else "allowed_when_required_by_contract",
            "generic": True,
        }

    def classify_step(self, step: dict[str, Any], *, index: int = 0) -> dict[str, Any]:
        explicit = self._explicit_policy(step)
        if explicit in {COMPILED_DIRECT, DYNAMIC_REFRESH, HYBRID}:
            return self._policy(step, explicit, ["explicit_contract_policy"], index=index)
        reasons: list[str] = []
        source_contract = step.get("source_contract") if isinstance(step.get("source_contract"), dict) else {}
        execution_contract = step.get("execution_contract") if isinstance(step.get("execution_contract"), dict) else {}
        capability_profile = step.get("capability_profile") if isinstance(step.get("capability_profile"), dict) else {}
        prompt_profile = step.get("prompt_profile") if isinstance(step.get("prompt_profile"), dict) else {}
        freshness_contract = self._first_dict(step, "freshness_contract", "refresh_policy", "source_policy")

        if bool(source_contract.get("requires_source_material")):
            reasons.append("source_contract_requires_source_material")
        if bool(freshness_contract.get("requires_refresh") or freshness_contract.get("refresh_each_run") or freshness_contract.get("live")):
            reasons.append("freshness_contract_requires_refresh")
        method = self._norm(execution_contract.get("execution_method") or execution_contract.get("method"))
        if method in self.dynamic_methods:
            reasons.append("execution_method_requires_dynamic_refresh")
        profile_method = self._norm(prompt_profile.get("prompt_profile") or prompt_profile.get("mode"))
        if profile_method in self.dynamic_methods:
            reasons.append("prompt_profile_requires_dynamic_refresh")
        cap_policy = self._first_dict(capability_profile, "reuse_policy", "execution_reuse_policy", "refresh_policy")
        cap_mode = self._norm(cap_policy.get("mode") or cap_policy.get("execution_mode"))
        if cap_mode in {DYNAMIC_REFRESH, "refresh_each_run", "live"}:
            reasons.append("capability_contract_requires_dynamic_refresh")
        if reasons:
            return self._policy(step, DYNAMIC_REFRESH, reasons, index=index)
        return self._policy(step, COMPILED_DIRECT, ["no_refresh_contract_detected"], index=index)

    def _policy(self, step: dict[str, Any], mode: str, reasons: list[str], *, index: int) -> dict[str, Any]:
        step_id = str(step.get("step_id") or step.get("compiled_step_id") or step.get("participant_id") or step.get("id") or f"step_{index:03d}").strip()
        return {
            "mode": mode,
            "scope": "step",
            "step_id": step_id,
            "policy_source": "compiled_contracts",
            "decision_reasons": reasons,
            "planning_policy": "do_not_replan_on_scheduled_run" if mode == COMPILED_DIRECT else "refresh_runtime_material_without_replanning_static_nodes",
            "verification_policy": "lightweight_structural" if mode == COMPILED_DIRECT else "runtime_result_verification",
            "generic": True,
        }

    def _explicit_policy(self, value: dict[str, Any]) -> str:
        candidates: list[Any] = []
        for key in ("execution_reuse_policy", "reuse_policy", "refresh_policy"):
            item = value.get(key)
            if isinstance(item, dict):
                candidates.extend([item.get("mode"), item.get("execution_mode")])
        return self._norm(next((x for x in candidates if x), ""))

    def _first_dict(self, value: dict[str, Any], *keys: str) -> dict[str, Any]:
        for key in keys:
            item = value.get(key) if isinstance(value, dict) else None
            if isinstance(item, dict):
                return item
        return {}

    def _norm(self, value: Any) -> str:
        return str(value or "").strip().replace("-", "_").casefold()
