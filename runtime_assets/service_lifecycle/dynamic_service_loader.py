from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any, Awaitable, Callable


@dataclass
class _LoadedService:
    service_id: str
    service_dir: Path
    manifest_path: Path
    module: ModuleType
    manifest: dict[str, Any]
    started: bool = False
    start_result: Any = None
    stop_callable: Any = None
    last_error: str | None = None
    loaded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class DynamicGeneratedServiceLoader:
    """Runtime-assets lifecycle supervisor for runtime-generated services.

    Boundary:
    - This is stable runtime infrastructure under runtime_assets.
    - It does not contain generated service behavior.
    - It dynamically discovers service manifests under runtime/generated/services
      while the process is already running, then loads and starts them.
    - Generated service directories are disposable runtime artifacts.
    """

    def __init__(
        self,
        *,
        services_dir: Path | str = Path("runtime") / "generated" / "services",
        trace_dir: Path | str = Path("runtime") / "traces" / "service_lifecycle",
        registry_path: Path | str = Path("runtime") / "registry" / "service_registry.json",
    ) -> None:
        self.services_dir = Path(services_dir)
        self.trace_dir = Path(trace_dir)
        self.registry_path = Path(registry_path)
        self._services: dict[str, _LoadedService] = {}
        self._task: asyncio.Task[Any] | None = None
        self._stopped = asyncio.Event()
        self._context: dict[str, Any] = {}

    def start(self, *, context: dict[str, Any] | None = None, scan_seconds: int = 3) -> None:
        if self._task and not self._task.done():
            return
        self._context = context or {}
        self._stopped = asyncio.Event()
        self._task = asyncio.create_task(self._loop(max(1, int(scan_seconds))))
        self._trace({"event": "dynamic_service_loader_started", "services_dir": str(self.services_dir)})

    async def stop(self) -> None:
        self._stopped.set()
        for service_id in list(self._services.keys()):
            await self._stop_service(service_id)
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._trace({"event": "dynamic_service_loader_stopped"})

    async def scan_once(self) -> list[dict[str, Any]]:
        self.services_dir.mkdir(parents=True, exist_ok=True)
        results: list[dict[str, Any]] = []
        for manifest_path in sorted(self.services_dir.glob("*/service_manifest.json")):
            result = await self._load_or_update(manifest_path)
            results.append(result)
        self._write_registry()
        return results

    async def _loop(self, scan_seconds: int) -> None:
        while not self._stopped.is_set():
            try:
                await self.scan_once()
            except Exception as exc:
                self._trace({"event": "dynamic_service_loader_scan_error", "error_type": exc.__class__.__name__, "error": str(exc)})
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=scan_seconds)
            except asyncio.TimeoutError:
                pass

    async def _load_or_update(self, manifest_path: Path) -> dict[str, Any]:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            self._trace({"event": "generated_service_manifest_invalid", "manifest_path": str(manifest_path), "error": str(exc)})
            return {"status": "invalid_manifest", "manifest_path": str(manifest_path), "error": str(exc)}
        if not isinstance(manifest, dict):
            return {"status": "invalid_manifest", "manifest_path": str(manifest_path)}
        service_id = str(manifest.get("service_id") or manifest_path.parent.name).strip()
        if not service_id:
            return {"status": "invalid_manifest", "reason": "missing_service_id", "manifest_path": str(manifest_path)}
        enabled = bool(manifest.get("enabled", True))
        if not enabled:
            if service_id in self._services:
                await self._stop_service(service_id)
            return {"status": "disabled", "service_id": service_id}
        existing = self._services.get(service_id)
        current_mtime = manifest_path.stat().st_mtime
        if existing and existing.started and existing.manifest_path.stat().st_mtime == current_mtime:
            return {"status": "already_running", "service_id": service_id}
        if existing:
            await self._stop_service(service_id)
        return await self._start_service(service_id=service_id, manifest=manifest, manifest_path=manifest_path)

    async def _start_service(self, *, service_id: str, manifest: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
        service_dir = manifest_path.parent
        entrypoint = manifest.get("entrypoint") if isinstance(manifest.get("entrypoint"), dict) else {}
        module_file = service_dir / str(entrypoint.get("module") or "service.py")
        start_name = str(entrypoint.get("start") or "start")
        stop_name = str(entrypoint.get("stop") or "stop")
        if not module_file.exists():
            result = {"status": "missing_entrypoint", "service_id": service_id, "module": str(module_file)}
            self._trace({"event": "generated_service_start_failed", **result})
            return result
        module_name = f"runtime_generated_service_{service_id}_{abs(hash(str(module_file)))}"
        spec = importlib.util.spec_from_file_location(module_name, module_file)
        if not spec or not spec.loader:
            return {"status": "invalid_entrypoint", "service_id": service_id}
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
            start_callable = getattr(module, start_name)
            stop_callable = getattr(module, stop_name, None)
            service_context = dict(self._context)
            service_context.update({
                "service_id": service_id,
                "service_dir": str(service_dir),
                "manifest": manifest,
                "trace_dir": str(self.trace_dir),
            })
            started = start_callable(service_context)
            if hasattr(started, "__await__"):
                started = await started
            self._services[service_id] = _LoadedService(
                service_id=service_id,
                service_dir=service_dir,
                manifest_path=manifest_path,
                module=module,
                manifest=manifest,
                started=True,
                start_result=started,
                stop_callable=stop_callable,
            )
            self._trace({"event": "generated_service_started", "service_id": service_id, "service_dir": str(service_dir), "start_result": _safe_json(started)})
            return {"status": "started", "service_id": service_id}
        except Exception as exc:
            self._trace({"event": "generated_service_start_failed", "service_id": service_id, "error_type": exc.__class__.__name__, "error": str(exc)})
            return {"status": "start_failed", "service_id": service_id, "error": str(exc), "error_type": exc.__class__.__name__}

    async def _stop_service(self, service_id: str) -> None:
        service = self._services.pop(service_id, None)
        if not service:
            return
        try:
            if callable(service.stop_callable):
                result = service.stop_callable(service.start_result)
                if hasattr(result, "__await__"):
                    await result
            self._trace({"event": "generated_service_stopped", "service_id": service_id})
        except Exception as exc:
            self._trace({"event": "generated_service_stop_failed", "service_id": service_id, "error_type": exc.__class__.__name__, "error": str(exc)})

    def _write_registry(self) -> None:
        try:
            self.registry_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "services": {
                    key: {
                        "service_id": svc.service_id,
                        "service_dir": str(svc.service_dir),
                        "manifest_path": str(svc.manifest_path),
                        "started": svc.started,
                        "loaded_at": svc.loaded_at,
                    }
                    for key, svc in sorted(self._services.items())
                },
            }
            self.registry_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            return

    def _trace(self, payload: dict[str, Any]) -> None:
        try:
            self.trace_dir.mkdir(parents=True, exist_ok=True)
            event = {"timestamp": datetime.now(timezone.utc).isoformat(), **payload}
            with (self.trace_dir / "dynamic_service_loader.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:
            return


def _safe_json(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)
