class BaseAgent:
    def __init__(self, name: str):
        self.name = name

    async def run(self, state: dict) -> dict:
        return state
