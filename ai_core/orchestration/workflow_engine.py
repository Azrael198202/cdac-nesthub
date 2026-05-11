from __future__ import annotations

from ai_core.config_loader import ConfigLoader
from ai_core.orchestration.node_executor import NodeExecutor
from ai_core.orchestration.state_manager import StateManager
from ai_core.validation.config_validator import ConfigValidator


class WorkflowEngine:
    def __init__(self, config_root: str = "configs"):
        self.loader = ConfigLoader(config_root)
        self.validator = ConfigValidator()
        self.node_executor = NodeExecutor()

    def load_workflow(self, workflow_path: str) -> dict:
        workflow = self.loader.load(workflow_path)
        self.validator.validate_workflow(workflow)
        return workflow

    async def run(self, workflow: dict, initial_state: dict | None = None) -> dict:
        state = StateManager.initialize(initial_state)
        for node in workflow.get("nodes", []):
            state = await self.node_executor.execute(node, state)
        return state
