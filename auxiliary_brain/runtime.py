from __future__ import annotations

from pathlib import Path
from typing import Any

from auxiliary_brain.community.builder import RuntimeCommunityBuilder
from auxiliary_brain.community.community_runtime import RuntimeCommunityEngine
from auxiliary_brain.community.registry import RuntimeCommunityRegistry
from auxiliary_brain.observability import RuntimeTraceLogger


class AuxiliaryBrainRuntime:
    """Parallel generic auxiliary runtime controlled by the main brain.

    It receives runtime-generated specifications, persists generated artifacts,
    and dispatches their neutral task graph. Domain behavior is delegated to
    generated specifications and external/generated tools.
    """

    ORIGIN = "auxiliary_brain"

    def __init__(self, runtime_root: str | Path = "runtime") -> None:
        self.runtime_root = Path(runtime_root)
        self.registry = RuntimeCommunityRegistry(self.runtime_root)
        self.builder = RuntimeCommunityBuilder()
        self.engine = RuntimeCommunityEngine()
        self.trace_logger = RuntimeTraceLogger(self.runtime_root)

    def create_from_specification(self, specification: dict[str, Any]) -> dict[str, Any]:
        definition = self.builder.build(specification)
        paths = self.registry.save_community(definition)
        trace = self.trace_logger.record(
            origin=self.ORIGIN,
            event_type="generated_artifacts_created",
            payload={"community_id": definition.community_id, "paths": paths},
        )
        return {
            "origin": self.ORIGIN,
            "status": "created",
            "community_id": definition.community_id,
            "paths": paths,
            "trace": trace,
            "definition": definition.to_dict(),
        }

    def run_specification(
        self,
        specification: dict[str, Any],
        provided_inputs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        definition = self.builder.build(specification)
        paths = self.registry.save_community(definition)
        result = self.engine.dispatch(definition, provided_inputs=provided_inputs)
        trace = self.trace_logger.record(
            origin=self.ORIGIN,
            event_type="generated_task_graph_dispatched",
            payload={
                "community_id": definition.community_id,
                "status": result.status,
                "executed_count": len(result.executed_task_ids),
                "blocked_count": len(result.blocked_task_ids),
            },
        )
        return {
            "origin": self.ORIGIN,
            "status": result.status,
            "community_id": definition.community_id,
            "paths": paths,
            "trace": trace,
            "result": result.to_dict(),
        }
