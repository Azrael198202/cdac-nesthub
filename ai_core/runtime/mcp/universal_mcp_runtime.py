from __future__ import annotations

from typing import Any, Protocol


class MCPTransport(Protocol):
    def call(self, server: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
        ...


class UniversalMCPRuntime:
    """A transport-neutral MCP orchestration facade."""

    def __init__(self, transport: MCPTransport | None = None) -> None:
        self.transport = transport
        self.registry: dict[str, dict[str, Any]] = {}

    def register_server(self, server_id: str, descriptor: dict[str, Any]) -> None:
        if not server_id:
            raise ValueError("server_id is required")
        self.registry[server_id] = dict(descriptor)

    def call_tool(self, server_id: str, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        if server_id not in self.registry:
            return {"status": "failed", "reason": "server_not_registered"}
        if self.transport is None:
            return {"status": "planned", "server_id": server_id, "tool_name": tool_name, "payload": payload}
        return self.transport.call(server_id, tool_name, payload)
