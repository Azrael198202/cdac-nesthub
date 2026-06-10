from __future__ import annotations

from typing import Any

from auxiliary_brain.runtime.capability.execution_mode_selector import ExecutionModeSelector
from auxiliary_brain.runtime.capability.runtime_native_provider import RuntimeNativeProvider
from auxiliary_brain.runtime.capability.structured_provider_router import StructuredProviderRouter


class CapabilityRouter:
    """Coordinates generic execution source routing."""

    def __init__(self) -> None:
        self.selector = ExecutionModeSelector()
        self.native = RuntimeNativeProvider()
        self.structured = StructuredProviderRouter()

    def select_mode(self, *, step: dict[str, Any], plan: dict[str, Any], state: dict[str, Any], capability: str) -> str:
        return self.selector.select(step=step, plan=plan, state=state, capability=capability)

    def try_runtime_native(self, *, run_id: str, node_id: str, step_id: str, capability: str, step: dict[str, Any], plan: dict[str, Any], state: dict[str, Any]) -> dict[str, Any] | None:
        if self.select_mode(step=step, plan=plan, state=state, capability=capability) != "runtime_native":
            return None
        return self.native.execute(run_id=run_id, node_id=node_id, step_id=step_id, capability=capability, step=step)
