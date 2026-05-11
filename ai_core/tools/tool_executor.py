from ai_core.tools.tool_registry import ToolRegistry


class ToolExecutor:
    def __init__(self):
        self.registry = ToolRegistry()

    def execute_tools(self, tools: list[str], state: dict) -> dict:
        enabled = self.registry.enabled_tools()
        return {
            "requested": tools,
            "executed": [tool for tool in tools if tool in enabled],
            "state": state,
        }
