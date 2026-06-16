from __future__ import annotations

from dataclasses import dataclass
from typing import Any


FAST_DETERMINISTIC = "fast_deterministic"
SLOW_EXTERNAL_RETRIEVAL = "slow_external_retrieval"
ITERATIVE_VALIDATION = "iterative_validation"
LONG_RUNNING_RUNTIME = "long_running_runtime"


@dataclass(frozen=True)
class ExecutionCharacteristicsClassifier:
    """Classify execution behavior from generic contracts only.

    The classifier does not inspect task names, participant names, capability
    names, or domain vocabulary. It reads structural contracts already present
    in the graph: source/freshness requirements, execution/reuse policy,
    prompt profile, and declared validation loops. The output drives progress
    heartbeat cadence, stale tolerance, and evidence/verification budgets.
    """

    heartbeat_seconds_fast: int = 10
    heartbeat_seconds_slow: int = 15
    heartbeat_seconds_long: int = 20
    timeout_seconds_fast: int = 60
    timeout_seconds_slow: int = 900
    timeout_seconds_long: int = 1800

    def apply_to_task_graph(self, task_graph: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(task_graph, dict):
            return task_graph
        graph = dict(task_graph)
        tasks = graph.get("tasks") if isinstance(graph.get("tasks"), list) else []
        out_tasks: list[dict[str, Any]] = []
        policies: list[dict[str, Any]] = []
        for index, step in enumerate(tasks, start=1):
            if not isinstance(step, dict):
                continue
            policy = self.classify_step(step, index=index)
            updated = dict(step)
            updated["execution_characteristics"] = policy
            if policy.get("evidence_budget") and not isinstance(updated.get("evidence_budget"), dict):
                updated["evidence_budget"] = policy["evidence_budget"]
            out_tasks.append(updated)
            policies.append(policy)
        graph["tasks"] = out_tasks
        graph["execution_characteristics"] = self.classify_task(policies)
        return graph

    def classify_task(self, step_policies: list[dict[str, Any]]) -> dict[str, Any]:
        normalized = [p for p in step_policies if isinstance(p, dict)]
        kinds = {str(p.get("kind") or FAST_DETERMINISTIC) for p in normalized}
        if not normalized:
            kind = FAST_DETERMINISTIC
        elif SLOW_EXTERNAL_RETRIEVAL in kinds:
            kind = SLOW_EXTERNAL_RETRIEVAL
        elif ITERATIVE_VALIDATION in kinds:
            kind = ITERATIVE_VALIDATION
        elif LONG_RUNNING_RUNTIME in kinds:
            kind = LONG_RUNNING_RUNTIME
        else:
            kind = FAST_DETERMINISTIC
        return {
            "scope": "task",
            "kind": kind,
            "heartbeat_seconds": max([int(p.get("heartbeat_seconds") or self.heartbeat_seconds_fast) for p in normalized] or [self.heartbeat_seconds_fast]),
            "timeout_seconds": max([int(p.get("timeout_seconds") or self.timeout_seconds_fast) for p in normalized] or [self.timeout_seconds_fast]),
            "stale_policy": "progress_aware",
            "generic": True,
        }

    def classify_step(self, step: dict[str, Any], *, index: int = 0) -> dict[str, Any]:
        step_id = str(step.get("step_id") or step.get("compiled_step_id") or step.get("participant_id") or step.get("id") or f"step_{index:03d}").strip()
        reasons: list[str] = []
        source_contract = self._first_dict(step, "source_contract", "source_policy", "execution_source_policy")
        freshness_contract = self._first_dict(step, "freshness_contract", "refresh_policy")
        execution_contract = self._first_dict(step, "execution_contract", "execution_reuse_policy", "reuse_policy")
        validation_contract = self._first_dict(step, "validation_contract", "verification_contract", "evidence_budget")
        prompt_profile = step.get("prompt_profile") if isinstance(step.get("prompt_profile"), dict) else {}

        if any(bool(source_contract.get(k)) for k in ("requires_source_material", "requires_live_evidence", "allow_external")):
            reasons.append("source_contract_requires_external_material")
        if any(bool(freshness_contract.get(k)) for k in ("requires_refresh", "refresh_each_run", "live")):
            reasons.append("freshness_contract_requires_refresh")
        method = self._norm(execution_contract.get("execution_method") or execution_contract.get("method") or execution_contract.get("mode"))
        if method in {"web_search", "source_retrieval", "external_source_retrieval", "remote_query", "provider_query", "live_query", "dynamic_refresh"}:
            reasons.append("execution_contract_requires_refreshable_source")
        profile = self._norm(prompt_profile.get("prompt_profile") or prompt_profile.get("mode"))
        if profile in {"source_retrieval", "web_search", "dynamic_refresh"}:
            reasons.append("prompt_profile_requires_source_retrieval")
        if any(str(validation_contract.get(k) or "").strip() for k in ("max_search_rounds", "max_validation_rounds", "max_retry_count")):
            reasons.append("validation_contract_declares_iteration_budget")

        if any("source" in reason or "refresh" in reason for reason in reasons):
            kind = SLOW_EXTERNAL_RETRIEVAL
            heartbeat = self.heartbeat_seconds_slow
            timeout = self.timeout_seconds_slow
            budget = self._budget(validation_contract)
        elif reasons:
            kind = ITERATIVE_VALIDATION
            heartbeat = self.heartbeat_seconds_slow
            timeout = self.timeout_seconds_slow
            budget = self._budget(validation_contract)
        else:
            kind = FAST_DETERMINISTIC
            heartbeat = self.heartbeat_seconds_fast
            timeout = self.timeout_seconds_fast
            budget = {}
        return {
            "scope": "step",
            "step_id": step_id,
            "kind": kind,
            "decision_reasons": reasons or ["no_long_running_contract_detected"],
            "heartbeat_seconds": heartbeat,
            "timeout_seconds": timeout,
            "evidence_budget": budget,
            "stale_policy": "expect_periodic_progress" if kind != FAST_DETERMINISTIC else "short_direct",
            "generic": True,
        }

    def _budget(self, value: dict[str, Any]) -> dict[str, int]:
        def _int(name: str, default: int) -> int:
            try:
                return max(1, int(value.get(name) or default))
            except Exception:
                return default
        return {
            "max_search_rounds": _int("max_search_rounds", 2),
            "max_validation_rounds": _int("max_validation_rounds", 2),
            "max_source_count": _int("max_source_count", 8),
            "max_retry_count": _int("max_retry_count", 1),
        }

    def _first_dict(self, value: dict[str, Any], *keys: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {}
        for key in keys:
            item = value.get(key)
            if isinstance(item, dict):
                return item
        return {}

    def _norm(self, value: Any) -> str:
        return str(value or "").strip().replace("-", "_").casefold()
