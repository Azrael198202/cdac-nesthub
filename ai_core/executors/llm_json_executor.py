from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import PROJECT_ROOT
from ai_core.executors.template_engine import TemplateEngine
from ai_core.validation.schema_validator import SchemaValidator
from ai_core.llm.provider_router import ProviderRouter


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

    async def execute(self, workflow_node: dict, node_config: dict, state: dict, capability_result: dict) -> dict:
        adapter = {}
        if node_config.get("adapter"):
            adapter_path = PROJECT_ROOT / node_config["adapter"]
            adapter = self.loader.load_yaml(adapter_path)

        prompt_path = PROJECT_ROOT / adapter.get("prompt", node_config["prompt"])
        schema_path = PROJECT_ROOT / adapter.get("output_schema", node_config["output_schema"])
        prompt = self.loader.load_yaml(prompt_path)
        schema = self.loader.load_json(schema_path)

        rendered = self.template.render(prompt.get("user_template", ""), {
            "user_input": state.get("input", ""),
            "previous_results": state.get("results", {}),
            "capability_result": capability_result,
            "human_feedback": state.get("human_feedback", []),
        })

        result = await self.router.generate_json(
            adapter=adapter,
            prompt=prompt,
            rendered_user_prompt=rendered,
            schema=schema,
        )

        self.validator.validate_data(result, schema)
        result["_executor_type"] = "llm_json"
        result["_node_id"] = node_config.get("node_id")
        result["_adapter_id"] = adapter.get("adapter_id")
        return result
