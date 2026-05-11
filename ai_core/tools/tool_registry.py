class ToolRegistry:
    def __init__(self):
        self._tools = {}

    def register(self, name: str, tool):
        self._tools[name] = tool

    def get(self, name: str):
        return self._tools.get(name)

    def list_tools(self):
        return sorted(self._tools.keys())
