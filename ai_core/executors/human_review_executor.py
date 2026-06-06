class HumanReviewExecutor:
    async def execute(self, workflow_node: dict, node_config: dict, state: dict, capability_result: dict) -> dict:
        return {'_executor_type':'human_review','_node_id':node_config.get('node_id'),'_status':'waiting_for_human_review'}
