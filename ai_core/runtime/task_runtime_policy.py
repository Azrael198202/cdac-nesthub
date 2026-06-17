from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ai_core.runtime.lifecycle_settings import RuntimeLifecycleSettingsStore


KNOWN_JOB_FAMILIES = {"capability_acquisition", "task_execution", "scheduled_execution", "dynamic_refresh"}


def _as_int(value: Any, default: int | None = None, *, minimum: int = 0, maximum: int = 86400) -> int | None:
    try:
        if value is None or value == "":
            return default
        parsed = int(float(value))
        return max(minimum, min(maximum, parsed))
    except Exception:
        return default


def _as_bool(value: Any, default: bool | None = None) -> bool | None:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


@dataclass(frozen=True)
class ResolvedRuntimePolicy:
    job_family: str
    timeout_seconds: int
    stale_after_seconds: int
    heartbeat_interval_seconds: int
    stale_watchdog_enabled: bool
    overlap_policy: str
    retry_policy: dict[str, Any]
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_family": self.job_family,
            "timeout_seconds": self.timeout_seconds,
            "stale_after_seconds": self.stale_after_seconds,
            "heartbeat_interval_seconds": self.heartbeat_interval_seconds,
            "stale_watchdog_enabled": self.stale_watchdog_enabled,
            "overlap_policy": self.overlap_policy,
            "retry_policy": self.retry_policy,
            "source": self.source,
        }


class TaskRuntimePolicyResolver:
    """Resolve lifecycle policy without hard-coding task names.

    The family is structural: a graph with schedule/trigger metadata is a
    scheduled execution.  The task identity remains available through task_id,
    task_name, and schedule_instance_id so each scheduled task can own its own
    interval and lifecycle override.
    """

    def __init__(self, settings_store: RuntimeLifecycleSettingsStore | None = None) -> None:
        self.settings_store = settings_store or RuntimeLifecycleSettingsStore()

    def family_from_graph(self, graph: dict[str, Any] | None, *, fallback: str = "task_execution") -> str:
        if not isinstance(graph, dict):
            return self._family(fallback)
        explicit = self._family(graph.get("execution_scope") or graph.get("job_family") or graph.get("_job_family"))
        if explicit:
            return explicit
        schedule_policy = _dict(graph.get("schedule_policy"))
        trigger_policy = _dict(graph.get("trigger_policy"))
        if schedule_policy or trigger_policy:
            mode = str(schedule_policy.get("mode") or trigger_policy.get("mode") or "").strip().lower()
            if mode and mode != "none":
                return "scheduled_execution"
        return self._family(fallback) or "task_execution"

    def resolve_for_graph(self, graph: dict[str, Any] | None, *, fallback_family: str = "task_execution") -> dict[str, Any]:
        family = self.family_from_graph(graph, fallback=fallback_family)
        base = self.settings_store.policy_for_family(family)
        merged = dict(base)
        source = [f"runtime_lifecycle_settings:{family}"]
        if isinstance(graph, dict):
            for block_name, block in self._override_blocks(graph):
                if not block:
                    continue
                source.append(block_name)
                self._merge_override(merged, block)
            task_id = str(graph.get("task_id") or graph.get("graph_id") or graph.get("task_name") or "").strip()
            task_name = str(graph.get("task_name") or graph.get("graph_id") or graph.get("task_id") or "").strip()
            if task_id:
                merged["task_id"] = task_id
            if task_name:
                merged["task_name"] = task_name
            schedule_policy = _dict(graph.get("schedule_policy"))
            schedule_instance_id = str(schedule_policy.get("schedule_instance_id") or graph.get("schedule_instance_id") or "").strip()
            if schedule_instance_id:
                merged["schedule_instance_id"] = schedule_instance_id
            if schedule_policy.get("interval_seconds") is not None:
                merged["interval_seconds"] = _as_int(schedule_policy.get("interval_seconds"), minimum=0)
            if schedule_policy.get("next_run_at") is not None:
                merged["next_run_at"] = schedule_policy.get("next_run_at")
        merged["job_family"] = family
        merged["source"] = " + ".join(source)
        normalized = self._normalize_policy(merged).to_dict()
        for key in ("task_id", "task_name", "schedule_instance_id", "interval_seconds", "next_run_at"):
            if key in merged and merged.get(key) is not None:
                normalized[key] = merged.get(key)
        return normalized

    def merge_into_metadata(self, *, metadata: dict[str, Any] | None, policy: dict[str, Any] | None) -> dict[str, Any]:
        out = dict(metadata or {})
        for key, value in (policy or {}).items():
            if value is not None:
                out[key] = value
        return out

    def _family(self, value: Any) -> str | None:
        text = str(value or "").strip().lower()
        return text if text in KNOWN_JOB_FAMILIES else None

    def _override_blocks(self, graph: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        schedule_policy = _dict(graph.get("schedule_policy"))
        trigger_policy = _dict(graph.get("trigger_policy"))
        return [
            ("task.runtime_policy", _dict(graph.get("runtime_policy"))),
            ("task.execution_policy", _dict(graph.get("execution_policy"))),
            ("schedule_policy.runtime_policy", _dict(schedule_policy.get("runtime_policy"))),
            ("trigger_policy.runtime_policy", _dict(trigger_policy.get("runtime_policy"))),
            ("schedule_policy", {k: v for k, v in schedule_policy.items() if k in self._policy_keys()}),
            ("trigger_policy", {k: v for k, v in trigger_policy.items() if k in self._policy_keys()}),
            ("scheduled_execution_scope.runtime_policy", _dict(_dict(graph.get("scheduled_execution_scope")).get("runtime_policy"))),
        ]

    def _policy_keys(self) -> set[str]:
        return {
            "timeout_seconds",
            "max_run_seconds",
            "max_runtime_seconds",
            "job_timeout_seconds",
            "stale_after_seconds",
            "watchdog_stale_seconds",
            "heartbeat_interval_seconds",
            "watchdog_heartbeat_interval_seconds",
            "stale_watchdog_enabled",
            "overlap_policy",
            "retry_policy",
        }

    def _merge_override(self, merged: dict[str, Any], override: dict[str, Any]) -> None:
        timeout = _as_int(
            override.get("timeout_seconds", override.get("max_run_seconds", override.get("max_runtime_seconds", override.get("job_timeout_seconds")))),
            None,
            minimum=0,
        )
        if timeout is not None:
            merged["timeout_seconds"] = timeout
        stale = _as_int(override.get("stale_after_seconds", override.get("watchdog_stale_seconds")), None, minimum=30)
        if stale is not None:
            merged["stale_after_seconds"] = stale
        heartbeat = _as_int(override.get("heartbeat_interval_seconds", override.get("watchdog_heartbeat_interval_seconds")), None, minimum=5, maximum=300)
        if heartbeat is not None:
            merged["heartbeat_interval_seconds"] = heartbeat
        watchdog = _as_bool(override.get("stale_watchdog_enabled"), None)
        if watchdog is not None:
            merged["stale_watchdog_enabled"] = watchdog
        overlap = str(override.get("overlap_policy") or "").strip()
        if overlap:
            merged["overlap_policy"] = overlap
        retry = override.get("retry_policy")
        if isinstance(retry, dict):
            merged["retry_policy"] = retry

    def _normalize_policy(self, policy: dict[str, Any]) -> ResolvedRuntimePolicy:
        family = self._family(policy.get("job_family")) or "task_execution"
        return ResolvedRuntimePolicy(
            job_family=family,
            timeout_seconds=_as_int(policy.get("timeout_seconds"), 3600, minimum=0) or 0,
            stale_after_seconds=_as_int(policy.get("stale_after_seconds"), 1200, minimum=30) or 1200,
            heartbeat_interval_seconds=_as_int(policy.get("heartbeat_interval_seconds"), 30, minimum=5, maximum=300) or 30,
            stale_watchdog_enabled=bool(_as_bool(policy.get("stale_watchdog_enabled"), True)),
            overlap_policy=str(policy.get("overlap_policy") or "skip_same_instance").strip() or "skip_same_instance",
            retry_policy=_dict(policy.get("retry_policy")),
            source=str(policy.get("source") or "runtime_lifecycle_settings"),
        )
