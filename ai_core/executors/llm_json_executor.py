from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import PROJECT_ROOT
from ai_core.executors.template_engine import TemplateEngine
from ai_core.validation.schema_validator import SchemaValidator
from ai_core.llm.provider_router import ProviderRouter
from ai_core.events.event_bus import event_bus
from ai_core.evolution.correction_learning import CorrectionLearningService


class LLMJsonExecutor:
    """
    Runtime-configured LLM JSON executor.

    No business/domain/task logic is allowed here.
    """

    def __init__(self) -> None:
        self.loader = ConfigLoader()
        self.template = TemplateEngine()
        self.validator = SchemaValidator()
        self.router = ProviderRouter()
        self.correction_learning = CorrectionLearningService()

    async def execute(self, workflow_node: dict, node_config: dict, state: dict, capability_result: dict) -> dict:
        run_id = state["run_id"]
        node_id = node_config.get("node_id")

        adapter = {}
        if node_config.get("adapter"):
            adapter_path = PROJECT_ROOT / node_config["adapter"]
            adapter = self.loader.load_yaml(adapter_path)

        prompt_path = PROJECT_ROOT / adapter.get("prompt", node_config["prompt"])
        schema_path = PROJECT_ROOT / adapter.get("output_schema", node_config["output_schema"])
        prompt = self.loader.load_yaml(prompt_path)
        schema = self.loader.load_json(schema_path)

        await event_bus.emit(run_id, {
            "type": "LLM_EXECUTOR_READY",
            "title": "LLM executor ready",
            "message": f"node={node_id}, adapter={adapter.get('adapter_id')}, prompt={prompt.get('id')}",
            "node_id": node_id,
            "adapter_id": adapter.get("adapter_id"),
            "prompt_id": prompt.get("id"),
        })

        correction_memory = self.correction_learning.build_prompt_reinforcement(
            node_id=node_id,
            user_input=state.get("input", ""),
        )

        rendered = self.template.render(prompt.get("user_template", ""), {
            "user_input": state.get("input", ""),
            "previous_results": state.get("results", {}),
            "capability_result": capability_result,
            "human_feedback": state.get("human_feedback", []),
            "correction_memory": correction_memory,
        })

        if correction_memory:
            rendered = rendered + "\n\n" + correction_memory
            await event_bus.emit(run_id, {
                "type": "CORRECTION_MEMORY_APPLIED",
                "title": "Correction memory applied",
                "message": f"Applied correction memory for node={node_id}.",
                "node_id": node_id,
            })

        await event_bus.emit(run_id, {
            "type": "LLM_PROMPT_RENDERED",
            "title": "Prompt rendered",
            "message": f"Rendered prompt length: {len(rendered)} characters",
            "node_id": node_id,
        })

        result = await self.router.generate_json(
            run_id=run_id,
            node_id=node_id,
            adapter=adapter,
            prompt=prompt,
            rendered_user_prompt=rendered,
            schema=schema,
        )

        await event_bus.emit(run_id, {
            "type": "LLM_JSON_VALIDATING",
            "title": "Validating JSON",
            "message": f"Validating result against schema: {schema_path}",
            "node_id": node_id,
        })

        self.validator.validate_data(result, schema)

        await event_bus.emit(run_id, {
            "type": "LLM_JSON_VALIDATED",
            "title": "JSON validated",
            "message": node_id,
            "node_id": node_id,
        })

        result["_executor_type"] = "llm_json"
        result["_node_id"] = node_id
        result["_adapter_id"] = adapter.get("adapter_id")
        return result
