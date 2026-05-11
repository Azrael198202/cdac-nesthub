from typing import Dict, Any, Optional
from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import RUNTIME_CONFIGS, RUNTIME_GENERATED, RUNTIME_REGISTRY


class CapabilityRegistry:
    def __init__(self) -> None:
        self.loader = ConfigLoader()

    def routes(self) -> Dict[str, Any]:
        return self.loader.load_yaml(RUNTIME_CONFIGS / "capabilities" / "capability_routes.yaml")

    def ids_for_node(self, node_id: str) -> list[str]:
        return self.routes().get("node_capability_map", {}).get(node_id, [])

    def find_spec(self, capability_id: str) -> Optional[Dict[str, Any]]:
        for d in [RUNTIME_CONFIGS / "capabilities", RUNTIME_GENERATED / "capabilities"]:
            for p in d.glob("*.yaml"):
                spec = self.loader.load_yaml(p)
                if spec.get("capability_id") == capability_id:
                    spec["_path"] = str(p)
                    return spec
        return None

    def mark_ready(self, capability_id: str, spec: Dict[str, Any]) -> None:
        p = RUNTIME_REGISTRY / "installed_capabilities.json"
        data = self.loader.load_json(p)
        data[capability_id] = {"status": "ready", "type": spec.get("type"), "spec_path": spec.get("_path", "")}
        self.loader.save_json(p, data)
