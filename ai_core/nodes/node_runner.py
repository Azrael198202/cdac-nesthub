from ai_core.nodes.node_config_loader import NodeConfigLoader
from ai_core.executors.executor_registry import ExecutorRegistry
class NodeRunner:
    """Generic node entry point. No business/domain/task-specific logic allowed."""
    def __init__(self): self.config_loader=NodeConfigLoader(); self.executor_registry=ExecutorRegistry()
    async def run(self, workflow_node: dict, state: dict, capability_result: dict) -> dict:
        node_config=self.config_loader.load(workflow_node)
        executor=self.executor_registry.get(node_config.get('executor_type'))
        return await executor.execute(workflow_node=workflow_node,node_config=node_config,state=state,capability_result=capability_result)
