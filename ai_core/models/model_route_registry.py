from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import RUNTIME_CONFIGS, RUNTIME_REGISTRY


@dataclass
class ModelRouteRegistrationResult:
    status: str
    model_id: str
    runtime: str
    route: str
    registry_path: str
    providers_path: str
    reason: str


class RuntimeModelRouteRegistry:
    """Register benchmark-approved models into runtime model routes.

    The route file remains runtime configuration. ai_core only performs generic
    read/modify/write operations after benchmark evidence proves the model can run.
    """

    def __init__(self) -> None:
        self.loader = ConfigLoader()
        self.providers_path = RUNTIME_CONFIGS / "models" / "providers.yaml"
        self.registry_path = RUNTIME_REGISTRY / "model_route_registry.json"
        RUNTIME_REGISTRY.mkdir(parents=True, exist_ok=True)
        self.providers_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.registry_path.exists():
            self.registry_path.write_text("{}", encoding="utf-8")

    def register_after_benchmark(self, *, candidate: dict[str, Any], benchmark: dict[str, Any], route: str = "runtime_discovered") -> dict[str, Any]:
        model_id = str(candidate.get("model_id") or benchmark.get("model_id") or "").strip()
        runtime = str(candidate.get("runtime") or benchmark.get("runtime") or "unknown")
        if not model_id:
            return asdict(ModelRouteRegistrationResult("failed", "unknown", runtime, route, str(self.registry_path), str(self.providers_path), "No model id was provided."))
        if not bool(benchmark.get("passed")):
            return asdict(ModelRouteRegistrationResult("blocked", model_id, runtime, route, str(self.registry_path), str(self.providers_path), "Benchmark did not pass; route not registered."))

        registry = self._load_json(self.registry_path)
        record_id = self._safe(f"{runtime}_{model_id}")
        record = {
            "model_id": model_id,
            "runtime": runtime,
            "route": route,
            "status": "active",
            "benchmark": benchmark,
            "candidate": candidate,
            "registered_at": datetime.now(timezone.utc).isoformat(),
        }
        registry[record_id] = record
        self.registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")

        providers = self.loader.load_yaml(self.providers_path) if self.providers_path.exists() else {}
        routes = providers.setdefault("routes", {})
        route_list = routes.setdefault(route, [])
        provider_name = self._provider_name(runtime, model_id)
        if provider_name not in route_list:
            route_list.insert(0, provider_name)
        provider_map = providers.setdefault("providers", {})
        provider_map[provider_name] = self._provider_config(runtime, model_id, candidate)
        self.loader.save_yaml(self.providers_path, providers)
        return asdict(ModelRouteRegistrationResult("registered", model_id, runtime, route, str(self.registry_path), str(self.providers_path), "Model route registered after benchmark."))

    def _provider_name(self, runtime: str, model_id: str) -> str:
        return self._safe(f"runtime_{runtime}_{model_id}")

    def _provider_config(self, runtime: str, model_id: str, candidate: dict[str, Any]) -> dict[str, Any]:
        if runtime == "ollama":
            return {
                "enabled": True,
                "type": "ollama",
                "base_url": "http://127.0.0.1:11434",
                "model": model_id,
                "timeout_seconds": 120,
                "source": "runtime_model_discovery",
            }
        return {
            "enabled": True,
            "type": "runtime_model",
            "runtime": runtime,
            "model": model_id,
            "local_path": candidate.get("local_path"),
            "timeout_seconds": 120,
            "source": "runtime_model_discovery",
        }

    def _load_json(self, path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8") or "{}")
        except Exception:
            return {}

    def _safe(self, value: str) -> str:
        return "".join(c if c.isalnum() else "_" for c in value).strip("_").lower()[:180] or "model"
