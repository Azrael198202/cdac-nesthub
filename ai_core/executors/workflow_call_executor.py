class WorkflowCallExecutor:
    async def execute(self, workflow_node: dict, node_config: dict, state: dict, capability_result: dict) -> dict:
        return {'_executor_type':'workflow_call','_node_id':node_config.get('node_id'),'_status':'workflow_call_ready'}
