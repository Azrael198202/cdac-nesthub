from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_CONFIGS


@dataclass
class RuntimeLifecycleSettings:
    """User-editable runtime lifecycle policy.

    These settings are generic runtime controls.  They are selected from
    execution scope metadata such as capability_acquisition, task_execution,
    scheduled_execution, and dynamic_refresh.  They intentionally do not use
    task names, capability names, agent names, or domain vocabulary.
    """

    default_timeout_seconds: int = 3600
    default_stale_after_seconds: int = 1200
    heartbeat_interval_seconds: int = 30
    capability_acquisition_timeout_seconds: int = 7200
    capability_acquisition_stale_after_seconds: int = 1800
    task_execution_timeout_seconds: int = 3600
    task_execution_stale_after_seconds: int = 1200
    scheduled_execution_timeout_seconds: int = 7200
    scheduled_execution_stale_after_seconds: int = 1800
    dynamic_refresh_timeout_seconds: int = 7200
    dynamic_refresh_stale_after_seconds: int = 1800
    capability_acquisition_stale_watchdog_enabled: bool = False
    task_execution_stale_watchdog_enabled: bool = True
    scheduled_execution_stale_watchdog_enabled: bool = True
    dynamic_refresh_stale_watchdog_enabled: bool = True
    known_job_families: list[str] = field(default_factory=lambda: [
        "capability_acquisition",
        "task_execution",
        "scheduled_execution",
        "dynamic_refresh",
    ])

    def normalized(self) -> "RuntimeLifecycleSettings":
        def bounded(value: Any, default: int, *, minimum: int, maximum: int) -> int:
            try:
                parsed = int(float(value))
            except Exception:
                parsed = default
            return max(minimum, min(maximum, parsed))

        self.default_timeout_seconds = bounded(self.default_timeout_seconds, 3600, minimum=0, maximum=86400)
        self.default_stale_after_seconds = bounded(self.default_stale_after_seconds, 1200, minimum=30, maximum=86400)
        self.heartbeat_interval_seconds = bounded(self.heartbeat_interval_seconds, 30, minimum=5, maximum=300)
        self.capability_acquisition_timeout_seconds = bounded(self.capability_acquisition_timeout_seconds, 7200, minimum=60, maximum=86400)
        self.capability_acquisition_stale_after_seconds = bounded(self.capability_acquisition_stale_after_seconds, 1800, minimum=60, maximum=86400)
        self.task_execution_timeout_seconds = bounded(self.task_execution_timeout_seconds, 3600, minimum=60, maximum=86400)
        self.task_execution_stale_after_seconds = bounded(self.task_execution_stale_after_seconds, 1200, minimum=60, maximum=86400)
        self.scheduled_execution_timeout_seconds = bounded(self.scheduled_execution_timeout_seconds, 7200, minimum=60, maximum=86400)
        self.scheduled_execution_stale_after_seconds = bounded(self.scheduled_execution_stale_after_seconds, 1800, minimum=60, maximum=86400)
        self.dynamic_refresh_timeout_seconds = bounded(self.dynamic_refresh_timeout_seconds, 7200, minimum=60, maximum=86400)
        self.dynamic_refresh_stale_after_seconds = bounded(self.dynamic_refresh_stale_after_seconds, 1800, minimum=60, maximum=86400)
        self.known_job_families = ["capability_acquisition", "task_execution", "scheduled_execution", "dynamic_refresh"]
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self.normalized())

    def policy_for_family(self, family: str | None) -> dict[str, Any]:
        settings = self.normalized()
        key = str(family or "").strip().lower()
        if key not in set(settings.known_job_families):
            key = "task_execution"
        if key == "capability_acquisition":
            timeout = settings.capability_acquisition_timeout_seconds
            stale = settings.capability_acquisition_stale_after_seconds
            watchdog = settings.capability_acquisition_stale_watchdog_enabled
        elif key == "scheduled_execution":
            timeout = settings.scheduled_execution_timeout_seconds
            stale = settings.scheduled_execution_stale_after_seconds
            watchdog = settings.scheduled_execution_stale_watchdog_enabled
        elif key == "dynamic_refresh":
            timeout = settings.dynamic_refresh_timeout_seconds
            stale = settings.dynamic_refresh_stale_after_seconds
            watchdog = settings.dynamic_refresh_stale_watchdog_enabled
        else:
            timeout = settings.task_execution_timeout_seconds
            stale = settings.task_execution_stale_after_seconds
            watchdog = settings.task_execution_stale_watchdog_enabled
        return {
            "job_family": key,
            "timeout_seconds": timeout,
            "stale_after_seconds": stale,
            "heartbeat_interval_seconds": settings.heartbeat_interval_seconds,
            "stale_watchdog_enabled": bool(watchdog),
        }


class RuntimeLifecycleSettingsStore:
    """JSON-backed lifecycle settings used by API, jobs, and scheduler."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (RUNTIME_CONFIGS / "runtime_lifecycle_settings.json")

    def defaults(self) -> RuntimeLifecycleSettings:
        return RuntimeLifecycleSettings().normalized()

    def load(self) -> RuntimeLifecycleSettings:
        default = self.defaults()
        if not self.path.exists():
            self.save(default.to_dict())
            return default
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        return self._from_payload({**default.to_dict(), **payload}).normalized()

    def save(self, payload: dict[str, Any] | RuntimeLifecycleSettings) -> dict[str, Any]:
        settings = payload if isinstance(payload, RuntimeLifecycleSettings) else self._from_payload(payload if isinstance(payload, dict) else {})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = settings.to_dict()
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)
        return data

    def as_api_payload(self) -> dict[str, Any]:
        data = self.load().to_dict()
        data["config_path"] = str(self.path)
        return data

    def policy_for_family(self, family: str | None) -> dict[str, Any]:
        policy = self.load().policy_for_family(family)
        # Environment variables remain emergency overrides, but source of truth
        # is the editable runtime settings file.
        env_map = {
            "capability_acquisition": (
                "AI_RUNTIME_CAPABILITY_ACQUISITION_TIMEOUT_SECONDS",
                "AI_RUNTIME_CAPABILITY_ACQUISITION_STALE_SECONDS",
            ),
            "task_execution": (
                "AI_RUNTIME_TASK_EXECUTION_TIMEOUT_SECONDS",
                "AI_RUNTIME_TASK_EXECUTION_STALE_SECONDS",
            ),
            "scheduled_execution": (
                "AI_RUNTIME_SCHEDULED_EXECUTION_TIMEOUT_SECONDS",
                "AI_RUNTIME_SCHEDULED_EXECUTION_STALE_SECONDS",
            ),
            "dynamic_refresh": (
                "AI_RUNTIME_DYNAMIC_REFRESH_TIMEOUT_SECONDS",
                "AI_RUNTIME_DYNAMIC_REFRESH_STALE_SECONDS",
            ),
        }
        timeout_env, stale_env = env_map.get(policy["job_family"], ("AI_RUNTIME_ASYNC_JOB_TIMEOUT_SECONDS", "AI_RUNTIME_ASYNC_JOB_STALE_SECONDS"))
        policy["timeout_seconds"] = self._int_env(timeout_env, policy["timeout_seconds"], minimum=0)
        policy["stale_after_seconds"] = self._int_env(stale_env, policy["stale_after_seconds"], minimum=30)
        policy["heartbeat_interval_seconds"] = self._int_env("AI_RUNTIME_ASYNC_JOB_HEARTBEAT_SECONDS", policy["heartbeat_interval_seconds"], minimum=5)
        return policy

    def _from_payload(self, payload: dict[str, Any]) -> RuntimeLifecycleSettings:
        current = self.defaults()
        data = payload if isinstance(payload, dict) else {}
        return RuntimeLifecycleSettings(
            default_timeout_seconds=data.get("default_timeout_seconds", current.default_timeout_seconds),
            default_stale_after_seconds=data.get("default_stale_after_seconds", current.default_stale_after_seconds),
            heartbeat_interval_seconds=data.get("heartbeat_interval_seconds", current.heartbeat_interval_seconds),
            capability_acquisition_timeout_seconds=data.get("capability_acquisition_timeout_seconds", current.capability_acquisition_timeout_seconds),
            capability_acquisition_stale_after_seconds=data.get("capability_acquisition_stale_after_seconds", current.capability_acquisition_stale_after_seconds),
            task_execution_timeout_seconds=data.get("task_execution_timeout_seconds", current.task_execution_timeout_seconds),
            task_execution_stale_after_seconds=data.get("task_execution_stale_after_seconds", current.task_execution_stale_after_seconds),
            scheduled_execution_timeout_seconds=data.get("scheduled_execution_timeout_seconds", current.scheduled_execution_timeout_seconds),
            scheduled_execution_stale_after_seconds=data.get("scheduled_execution_stale_after_seconds", current.scheduled_execution_stale_after_seconds),
            dynamic_refresh_timeout_seconds=data.get("dynamic_refresh_timeout_seconds", current.dynamic_refresh_timeout_seconds),
            dynamic_refresh_stale_after_seconds=data.get("dynamic_refresh_stale_after_seconds", current.dynamic_refresh_stale_after_seconds),
            capability_acquisition_stale_watchdog_enabled=bool(data.get("capability_acquisition_stale_watchdog_enabled", current.capability_acquisition_stale_watchdog_enabled)),
            task_execution_stale_watchdog_enabled=bool(data.get("task_execution_stale_watchdog_enabled", current.task_execution_stale_watchdog_enabled)),
            scheduled_execution_stale_watchdog_enabled=bool(data.get("scheduled_execution_stale_watchdog_enabled", current.scheduled_execution_stale_watchdog_enabled)),
            dynamic_refresh_stale_watchdog_enabled=bool(data.get("dynamic_refresh_stale_watchdog_enabled", current.dynamic_refresh_stale_watchdog_enabled)),
        )

    @staticmethod
    def _int_env(name: str, default: int, *, minimum: int) -> int:
        try:
            value = os.getenv(name)
            if value is None or value == "":
                return int(default)
            return max(minimum, int(float(value)))
        except Exception:
            return int(default)
