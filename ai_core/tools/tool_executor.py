class ToolExecutor:
    async def execute(self, tool, **kwargs):
        if tool is None:
            raise ValueError("Tool not found")
        return tool(**kwargs)
