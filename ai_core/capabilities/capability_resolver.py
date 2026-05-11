from typing import Tuple, Dict, Any
from ai_core.events.event_bus import event_bus
from ai_core.capabilities.capability_registry import CapabilityRegistry
from ai_core.capabilities.capability_spec_generator import CapabilitySpecGenerator


class CapabilityResolver:
    def __init__(self) -> None:
        self.registry = CapabilityRegistry()
        self.generator = CapabilitySpecGenerator()

    async def ensure_for_node(self, run_id: str, node_id: str, context: dict) -> Tuple[bool, Dict[str, Any]]:
        cap_ids = self.registry.ids_for_node(node_id)
        if not cap_ids:
            cap_ids = ["unknown_runtime_capability"]

        for cap_id in cap_ids:
            await event_bus.emit(run_id, {"type": "CAPABILITY_ROUTE", "title": "Checking capability", "message": cap_id})
            spec = self.registry.find_spec(cap_id)
            if not spec:
                spec = self.generator.generate(cap_id, node_id, context)
                return False, {
                    "approval_required": True,
                    "pending_kind": "capability_spec_review",
                    "capability_id": cap_id,
                    "spec": spec,
                    "message": f"Generated a new capability spec for {cap_id}."
                }

            self.registry.mark_ready(cap_id, spec)
            await event_bus.emit(run_id, {"type": "CAPABILITY_READY", "title": "Capability ready", "message": cap_id})
            return True, {"capability_id": cap_id, "type": spec.get("type"), "spec": spec}

        return False, {"approval_required": False, "message": "No capability available."}

    async def install_start_verify(self, run_id: str, spec: dict) -> bool:
        self.registry.mark_ready(spec["capability_id"], spec)
        await event_bus.emit(run_id, {"type": "CAPABILITY_READY", "title": "Capability registered", "message": spec["capability_id"], "progress": 100})
        return True
