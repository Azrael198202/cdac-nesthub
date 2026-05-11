from typing import Tuple, Dict, Any
from ai_core.events.event_bus import event_bus
from ai_core.capabilities.capability_registry import CapabilityRegistry
from ai_core.capabilities.capability_spec_generator import CapabilitySpecGenerator
from ai_core.capabilities.capability_verifier import CapabilityVerifier
from ai_core.capabilities.capability_installer import CapabilityInstaller
from ai_core.capabilities.capability_runtime_registrar import CapabilityRuntimeRegistrar


class CapabilityResolver:
    def __init__(self) -> None:
        self.registry = CapabilityRegistry()
        self.generator = CapabilitySpecGenerator()
        self.verifier = CapabilityVerifier()
        self.installer = CapabilityInstaller()
        self.registrar = CapabilityRuntimeRegistrar()

    async def ensure_for_node(self, run_id: str, node_id: str, task_context: dict) -> Tuple[bool, Dict[str, Any]]:
        cap_ids = self.registry.capability_ids_for_node(node_id) or ["unknown_runtime_capability"]
        last_result = {}
        for cap_id in cap_ids:
            ok, result = await self.ensure_capability(run_id, cap_id, node_id, task_context)
            if ok:
                return True, result
            if result.get("approval_required"):
                return False, result
            last_result = result
        return False, last_result or {"reason": "no_capability_available", "message": f"No capability available for node: {node_id}", "approval_required": False}

    async def ensure_capability(self, run_id: str, capability_id: str, node_id: str, task_context: dict) -> Tuple[bool, Dict[str, Any]]:
        await event_bus.emit(run_id, {"type": "CAPABILITY_ROUTE", "title": "Resolving capability", "message": capability_id, "capability_id": capability_id})
        spec = self.registry.find_spec(capability_id)
        if not spec:
            spec = self.generator.generate(capability_id, node_id, task_context)
            path = self.registry.save_generated_spec(spec)
            spec["_path"] = str(path)
            return False, {"reason": "generated_capability_spec_requires_review", "capability_id": capability_id, "spec": spec, "approval_required": True, "pending_kind": "capability_spec_review", "message": f"Generated new capability spec for '{capability_id}'. Please review before installing."}
        satisfied, reason = await self.verifier.is_satisfied(run_id, spec)
        if satisfied:
            self.registrar.register(spec["capability_id"], spec, "ready")
            return True, {"capability_id": spec["capability_id"], "type": spec.get("type"), "status": "ready", "spec": spec}
        return False, {"reason": "capability_not_satisfied", "capability_id": spec["capability_id"], "spec": spec, "approval_required": spec.get("security", {}).get("approval_required", True), "pending_kind": "capability_install", "message": f"Capability '{spec['capability_id']}' is not ready: {reason}"}

    async def install_start_verify(self, run_id: str, spec: dict) -> bool:
        await event_bus.emit(run_id, {"type": "CAPABILITY_INSTALL_BEGIN", "title": "Installing capability", "message": spec.get("capability_id"), "progress": 20})
        if not await self.installer.install(run_id, spec):
            await event_bus.emit(run_id, {"type": "CAPABILITY_INSTALL_FAILED", "title": "Capability install failed", "message": spec.get("capability_id")})
            return False
        if not await self.installer.start(run_id, spec):
            await event_bus.emit(run_id, {"type": "CAPABILITY_START_FAILED", "title": "Capability start failed", "message": spec.get("capability_id")})
            return False
        ok, reason = await self.verifier.is_satisfied(run_id, spec)
        if not ok:
            await event_bus.emit(run_id, {"type": "CAPABILITY_VERIFY_FAILED", "title": "Capability verify failed", "message": reason})
            return False
        self.registrar.register(spec["capability_id"], spec, "ready")
        await event_bus.emit(run_id, {"type": "CAPABILITY_READY", "title": "Capability ready", "message": spec.get("capability_id"), "progress": 100})
        return True
