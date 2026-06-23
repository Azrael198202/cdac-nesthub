from __future__ import annotations

from typing import Any

from .capability_task_graph_compiler import CapabilityTaskGraphCompiler


class CapabilityRequestSplitter:
    def split(self, **kwargs: Any) -> dict[str, Any]:
        return CapabilityTaskGraphCompiler().compile(**kwargs)
