from datetime import datetime
from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import RUNTIME_REGISTRY


class CapabilityRuntimeRegistrar:
    def __init__(self) -> None:
        self.loader = ConfigLoader()

    def register(self, capability_id: str, spec: dict, status: str = "ready") -> None:
        installed_path = RUNTIME_REGISTRY / "installed_capabilities.json"
        provider_path = RUNTIME_REGISTRY / "provider_registry.json"
        tool_path = RUNTIME_REGISTRY / "tool_registry.json"
        installed = self.loader.load_json(installed_path)
        installed[capability_id] = {"status": status, "type": spec.get("type"), "updated_at": datetime.utcnow().isoformat(), "spec_path": spec.get("_path", "")}
        self.loader.save_json(installed_path, installed)
        reg = spec.get("runtime_register", {})
        if reg.get("provider_name"):
            providers = self.loader.load_json(provider_path)
            providers[reg["provider_name"]] = {"capability_id": capability_id, "type": spec.get("type"), "updated_at": datetime.utcnow().isoformat()}
            self.loader.save_json(provider_path, providers)
        if reg.get("tool_name"):
            tools = self.loader.load_json(tool_path)
            tools[reg["tool_name"]] = {"capability_id": capability_id, "type": spec.get("type"), "updated_at": datetime.utcnow().isoformat()}
            self.loader.save_json(tool_path, tools)
