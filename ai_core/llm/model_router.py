class ModelRouter:
    def __init__(self, provider_manager):
        self.provider_manager = provider_manager

    async def ensure_model_for_task(self, run_id: str, task_type: str):
        return await self.provider_manager.ensure_any_provider_ready(run_id, task_type)
