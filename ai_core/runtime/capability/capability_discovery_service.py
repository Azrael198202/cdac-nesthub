from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ai_core.config.paths import RUNTIME_GENERATED
from ai_core.llm.provider_router import ProviderRouter
from ai_core.runtime.mcp.mcp_registry import MCPRegistry


class CapabilityDiscoveryService:
    """Discovers missing capabilities through MCP manifests and strong models.

    Discovery results are written to runtime/generated so source code remains
    generic. This service can be called when a capability is absent from the
    current topology or local registry.
    """

    OUT_PATH = RUNTIME_GENERATED / "capabilities" / "discovered_capabilities.json"

    def __init__(self) -> None:
        self.mcp = MCPRegistry()
        self.router = ProviderRouter()

    async def discover(self, *, run_id: str, capability: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        existing = self.mcp.find_capability(capability)
        if existing:
            result = {"status": "found_in_mcp", "capability": capability, "contract": existing}
            self._persist(result)
            return result
        schema = {"type": "object", "additionalProperties": True}
        prompt = {
            "system": (
                "You are a generic runtime capability discovery planner. Given an unknown capability, "
                "propose source category, candidate execution modes, MCP/tool discovery hints, and model tier needs. "
                "Do not write business implementation code. Return JSON only."
            ),
            "user": json.dumps({"capability": capability, "context": context or {}}, ensure_ascii=False),
        }
        adapter = {"task_type": "unknown_capability_discovery", "provider_route": ["openai", "claude", "ollama"]}
        try:
            contract = await self.router.generate_json(
                run_id=run_id,
                node_id="capability_discovery",
                adapter=adapter,
                prompt=prompt,
                rendered_user_prompt=prompt["user"],
                schema=schema,
            )
            result = {"status": "generated", "capability": capability, "contract": contract}
        except Exception as exc:
            result = {"status": "deferred", "capability": capability, "error": str(exc), "contract": {}}
        self._persist(result)
        return result

    def _persist(self, result: dict[str, Any]) -> None:
        self.OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        data: list[Any] = []
        if self.OUT_PATH.exists():
            try:
                loaded = json.loads(self.OUT_PATH.read_text(encoding="utf-8"))
                if isinstance(loaded, list): data = loaded
            except Exception:
                data = []
        data.append({**result, "recorded_at": datetime.now(timezone.utc).isoformat()})
        self.OUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
