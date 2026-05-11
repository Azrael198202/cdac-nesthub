from ai_core.agents.base_agent import BaseAgent


class AgentRegistry:
    def __init__(self):
        self.agents: dict[str, BaseAgent] = {}

    def register(self, agent: BaseAgent) -> None:
        self.agents[agent.name] = agent

    def get(self, name: str) -> BaseAgent | None:
        return self.agents.get(name)
