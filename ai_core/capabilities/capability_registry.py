from pathlib import Path
from typing import Dict, Any, Optional
from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import RUNTIME_CONFIGS, RUNTIME_GENERATED, RUNTIME_REGISTRY


class CapabilityRegistry:
    def __init__(self) -> None:
        self.loader = ConfigLoader()
        self.config_dirs = [RUNTIME_CONFIGS / "capabilities", RUNTIME_GENERATED / "capabilities"]

    def load_routes(self) -> Dict[str, Any]:
        return self.loader.load_yaml(RUNTIME_CONFIGS / "capabilities" / "capability_routes.yaml")

    def capability_ids_for_node(self, node_id: str) -> list[str]:
        routes = self.load_routes()
        return routes.get("node_capability_map", {}).get(node_id, routes.get("default_route", []))

    def find_spec(self, capability_id: str) -> Optional[Dict[str, Any]]:
        for d in self.config_dirs:
            if not d.exists():
                continue
            for path in d.glob("*.yaml"):
                data = self.loader.load_yaml(path)
                if data.get("capability_id") == capability_id:
                    data["_path"] = str(path)
                    return data
        return None

    def save_generated_spec(self, spec: Dict[str, Any]) -> Path:
        cap_id = spec["capability_id"]
        p = RUNTIME_GENERATED / "capabilities" / f"{cap_id}.yaml"
        self.loader.save_yaml(p, spec)
        return p

    def mark_installed(self, capability_id: str, data: Dict[str, Any]) -> None:
        p = RUNTIME_REGISTRY / "installed_capabilities.json"
        registry = self.loader.load_json(p)
        registry[capability_id] = data
        self.loader.save_json(p, registry)
