from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


@dataclass
class RuntimeServiceRecord:
    """Durable metadata for a runtime-managed background service.

    The record is intentionally generic.  It describes a service lifecycle and
    the runtime components it coordinates, but it does not encode task, agent,
    or capability-specific behavior.
    """

    service_id: str
    name: str
    service_type: str
    status: str = "created"
    run_mode: str = "background"
    enabled: bool = False
    configuration: dict[str, Any] | None = None
    source: str = "runtime_service_manager"
    created_at: str | None = None
    updated_at: str | None = None
    started_at: str | None = None
    stopped_at: str | None = None
    last_error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["configuration"] = payload.get("configuration") or {}
        return payload


class RuntimeServiceManager:
    """Manage runtime service records and lifecycle handlers.

    This is the generic service-control layer. Concrete background workers are
    registered as handlers at process startup. The manager stores metadata under
    runtime/generated/services and writes lifecycle traces under
    runtime/traces/service_lifecycle.
    """

    def __init__(self, *, service_dir: Path | str = Path("runtime") / "generated" / "services", trace_dir: Path | str = Path("runtime") / "traces" / "service_lifecycle") -> None:
        self.service_dir = Path(service_dir)
        self.trace_dir = Path(trace_dir)
        self._start_handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}
        self._stop_handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}
        self._status_handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}

    def register_handler(
        self,
        service_type: str,
        *,
        start: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        stop: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        status: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        key = self._key(service_type)
        if start:
            self._start_handlers[key] = start
        if stop:
            self._stop_handlers[key] = stop
        if status:
            self._status_handlers[key] = status

    def create_service(self, *, service_id: str, name: str | None = None, service_type: str, configuration: dict[str, Any] | None = None, enabled: bool = False) -> dict[str, Any]:
        sid = self._safe_id(service_id)
        now = self._now()
        existing = self.get_service(sid)
        record = RuntimeServiceRecord(
            service_id=sid,
            name=str(name or sid),
            service_type=self._key(service_type),
            status=str(existing.get("status") if existing else "created"),
            enabled=bool(existing.get("enabled") if existing else enabled),
            configuration=configuration if isinstance(configuration, dict) else {},
            created_at=str(existing.get("created_at") if existing else now),
            updated_at=now,
            started_at=existing.get("started_at") if existing else None,
            stopped_at=existing.get("stopped_at") if existing else None,
            last_error=existing.get("last_error") if existing else None,
        )
        self._write(record.to_dict())
        self._trace({"event": "service_created", "service_id": sid, "service_type": record.service_type, "enabled": record.enabled})
        if enabled:
            return self.start_service(sid)
        return {"ok": True, "status": record.status, "service": record.to_dict()}

    def start_service(self, service_id: str) -> dict[str, Any]:
        record = self.get_service(service_id)
        if not record:
            return {"ok": False, "status": "not_found", "service_id": service_id}
        service_type = self._key(record.get("service_type"))
        handler = self._start_handlers.get(service_type)
        now = self._now()
        if not handler:
            record.update({"status": "unavailable", "enabled": False, "updated_at": now, "last_error": {"code": "missing_start_handler", "message": "No start handler is registered for this runtime service type."}})
            self._write(record)
            self._trace({"event": "service_start_unavailable", "service_id": record.get("service_id"), "service_type": service_type})
            return {"ok": False, "status": "unavailable", "service": record}
        try:
            result = handler(record.get("configuration") if isinstance(record.get("configuration"), dict) else {})
            record.update({"status": "running", "enabled": True, "started_at": now, "updated_at": now, "last_error": None})
            record["runtime_result"] = result if isinstance(result, dict) else {"value": result}
            self._write(record)
            self._trace({"event": "service_started", "service_id": record.get("service_id"), "service_type": service_type, "result": record.get("runtime_result")})
            return {"ok": True, "status": "running", "service": record}
        except Exception as exc:
            record.update({"status": "failed", "enabled": False, "updated_at": now, "last_error": {"type": exc.__class__.__name__, "message": str(exc)}})
            self._write(record)
            self._trace({"event": "service_start_failed", "service_id": record.get("service_id"), "service_type": service_type, "error": record.get("last_error")})
            return {"ok": False, "status": "failed", "service": record}

    def stop_service(self, service_id: str) -> dict[str, Any]:
        record = self.get_service(service_id)
        if not record:
            return {"ok": False, "status": "not_found", "service_id": service_id}
        service_type = self._key(record.get("service_type"))
        handler = self._stop_handlers.get(service_type)
        now = self._now()
        try:
            result = handler(record.get("configuration") if isinstance(record.get("configuration"), dict) else {}) if handler else {"status": "no_stop_handler"}
            record.update({"status": "stopped", "enabled": False, "stopped_at": now, "updated_at": now, "runtime_result": result if isinstance(result, dict) else {"value": result}})
            self._write(record)
            self._trace({"event": "service_stopped", "service_id": record.get("service_id"), "service_type": service_type})
            return {"ok": True, "status": "stopped", "service": record}
        except Exception as exc:
            record.update({"status": "failed", "updated_at": now, "last_error": {"type": exc.__class__.__name__, "message": str(exc)}})
            self._write(record)
            self._trace({"event": "service_stop_failed", "service_id": record.get("service_id"), "service_type": service_type, "error": record.get("last_error")})
            return {"ok": False, "status": "failed", "service": record}

    def status_service(self, service_id: str) -> dict[str, Any]:
        record = self.get_service(service_id)
        if not record:
            return {"ok": False, "status": "not_found", "service_id": service_id}
        handler = self._status_handlers.get(self._key(record.get("service_type")))
        runtime_status = handler(record.get("configuration") if isinstance(record.get("configuration"), dict) else {}) if handler else {}
        if isinstance(runtime_status, dict):
            record = dict(record)
            record["runtime_status"] = runtime_status
        return {"ok": True, "status": record.get("status") or "unknown", "service": record}

    def get_service(self, service_id: str) -> dict[str, Any] | None:
        path = self._path(service_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return value if isinstance(value, dict) else None

    def list_services(self) -> list[dict[str, Any]]:
        try:
            self.service_dir.mkdir(parents=True, exist_ok=True)
            items = []
            for path in self.service_dir.glob("*.json"):
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if isinstance(value, dict):
                    items.append(value)
            items.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)
            return items
        except Exception:
            return []

    def suggest_service_for_context(self, context: dict[str, Any]) -> dict[str, Any] | None:
        """Return a generic runtime-service suggestion for a task context.

        The suggestion is derived from structural execution policy, not from a
        business capability name. If a task graph declares a durable recurring
        policy, the runtime can propose a background dispatcher service.
        """
        policy = context.get("schedule_policy") if isinstance(context.get("schedule_policy"), dict) else {}
        if not (policy.get("enabled") is True and str(policy.get("mode") or "") == "recurring"):
            return None
        services = self.list_services()
        has_running_dispatcher = any(
            str(item.get("service_type") or "") == "durable_task_dispatcher" and item.get("enabled") is True and str(item.get("status") or "") == "running"
            for item in services
        )
        if has_running_dispatcher:
            return None
        return {
            "kind": "runtime_service_suggestion",
            "service_type": "durable_task_dispatcher",
            "service_id": "durable_task_dispatcher",
            "name": "Durable Task Dispatcher",
            "reason": "A durable recurring execution policy exists, but no running background dispatcher service was found.",
            "suggested_commands": [
                "Create runtime service named Durable Task Dispatcher.",
                "Start runtime service Durable Task Dispatcher.",
            ],
        }

    def _write(self, record: dict[str, Any]) -> None:
        self.service_dir.mkdir(parents=True, exist_ok=True)
        self._path(str(record.get("service_id") or "runtime_service")).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    def _path(self, service_id: str) -> Path:
        return self.service_dir / f"{self._safe_id(service_id)}.json"

    def _trace(self, payload: dict[str, Any]) -> None:
        try:
            self.trace_dir.mkdir(parents=True, exist_ok=True)
            with (self.trace_dir / "runtime_services.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"timestamp": self._now(), **payload}, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _safe_id(self, value: str) -> str:
        text = str(value or "runtime_service").strip().replace(" ", "_")
        allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        safe = "".join(ch for ch in text if ch in allowed).strip("_-")
        return safe or "runtime_service"

    def _key(self, value: Any) -> str:
        return str(value or "runtime_service").strip().lower().replace(" ", "_")

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
