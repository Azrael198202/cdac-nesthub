from __future__ import annotations

from ai_core.llm.model_router import ModelRouter
from ai_core.tools.tool_executor import ToolExecutor
from ai_core.memory.memory_manager import MemoryManager


class NodeExecutor:
    def __init__(self):
        self.model_router = ModelRouter()
        self.tool_executor = ToolExecutor()
        self.memory = MemoryManager()

    async def execute(self, node: dict, state: dict):
        node_type = node.get("type")

        if node_type == "intent":
            return await self._run_intent(node, state)
        if node_type == "planner":
            return await self._run_planner(node, state)
        if node_type == "executor":
            return await self._run_executor(node, state)
        if node_type == "context":
            return await self._run_context(node, state)
        return state

    async def _run_intent(self, node: dict, state: dict) -> dict:
        model_cfg = self.model_router.resolve(node)
        result = {"type": "intent", "model": model_cfg, "state": state}
        return {**state, "intent": result}

    async def _run_planner(self, node: dict, state: dict) -> dict:
        model_cfg = self.model_router.resolve(node)
        result = {"type": "planner", "model": model_cfg, "state": state}
        return {**state, "plan": result}

    async def _run_executor(self, node: dict, state: dict) -> dict:
        tools = node.get("tools", [])
        execution = self.tool_executor.execute_tools(tools, state)
        return {**state, "execution": execution}

    async def _run_context(self, node: dict, state: dict) -> dict:
        updated_state = dict(state)
        for memory_name, enabled in node.get("memory", {}).items():
            if enabled:
                self.memory.remember(memory_name, state)
                updated_state.setdefault("memory", []).append(memory_name)
        return updated_state
