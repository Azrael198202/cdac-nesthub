class ToolExecutor:
    async def execute(self, tool, **kwargs):
        if tool is None:
            raise ValueError("Tool not found")
        result = tool(**kwargs)
        return result
