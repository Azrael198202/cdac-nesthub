from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import PROJECT_ROOT
from ai_core.executors.template_engine import TemplateEngine
from ai_core.validation.schema_validator import SchemaValidator
from ai_core.llm.provider_router import ProviderRouter
from ai_core.events.event_bus import event_bus
from ai_core.validation.recoverable_validation_error import RecoverableValidationError
from ai_core.validation.schema_auto_repair import SchemaAutoRepair
from ai_core.validation.result_auto_repair import ResultAutoRepair
from ai_core.evolution.runtime_learning import RuntimeLearningService


class LLMJsonExecutor:
    """
    Runtime-configured LLM JSON executor.

    No business/domain/task logic is allowed here.
    """

    def __init__(self) -> None:
        self.loader = ConfigLoader()
        self.template = TemplateEngine()
        self.validator = SchemaValidator()
        self.schema_auto_repair = SchemaAutoRepair()
        self.result_auto_repair = ResultAutoRepair()
        self.router = ProviderRouter()
        self.runtime_learning = RuntimeLearningService()

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

        correction_memory = self.runtime_learning.build_prompt_reinforcement(
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

        runtime_rules = prompt.get("runtime_rules", [])
        if runtime_rules:
            rendered = rendered + "\n\nRuntime rules:\n" + "\n".join(f"- {r}" for r in runtime_rules)

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

        try:
            self.validator.validate_data(result, schema)
        except Exception as exc:
            original_error = str(exc)

            # 1. First try to repair the RESULT.
            # This is for cases where the schema is correct but the model omitted required fields.
            result_repaired, repaired_result, result_changes = self.result_auto_repair.try_repair(
                node_id=node_id,
                result=result,
                schema=schema,
                state=state,
                error_message=original_error,
            )

            if result_repaired:
                await event_bus.emit(run_id, {
                    "type": "RESULT_AUTO_REPAIRED",
                    "title": "Result auto-repaired",
                    "message": f"Missing or incompatible fields repaired for node={node_id}. Changes: {result_changes}",
                    "node_id": node_id,
                    "changes": result_changes,
                    "result": repaired_result,
                })

                try:
                    self.validator.validate_data(repaired_result, schema)
                    result = repaired_result
                    await event_bus.emit(run_id, {
                        "type": "LLM_JSON_VALIDATED",
                        "title": "JSON validated after result repair",
                        "message": node_id,
                        "node_id": node_id,
                    })
                except Exception as result_repair_exc:
                    # Continue to schema repair using repaired result, because it may still be structurally better.
                    result = repaired_result
                    original_error = str(result_repair_exc)

            # 2. If still invalid, try to repair SCHEMA.
            try:
                self.validator.validate_data(result, schema)
            except Exception as after_result_exc:
                original_error = str(after_result_exc)

                repaired, repaired_schema, changes = self.schema_auto_repair.try_repair(
                    node_id=node_id,
                    schema_path=str(schema_path),
                    schema=schema,
                    result=result,
                    error_message=original_error,
                )

                if repaired:
                    await event_bus.emit(run_id, {
                        "type": "SCHEMA_AUTO_REPAIRED",
                        "title": "Schema auto-repaired",
                        "message": f"Schema evolved automatically for node={node_id}. Changes: {changes}",
                        "node_id": node_id,
                        "schema_path": str(schema_path),
                        "changes": changes,
                    })

                    try:
                        self.validator.validate_data(result, repaired_schema)
                        await event_bus.emit(run_id, {
                            "type": "LLM_JSON_VALIDATED",
                            "title": "JSON validated after schema repair",
                            "message": node_id,
                            "node_id": node_id,
                        })
                    except Exception as second_exc:
                        await event_bus.emit(run_id, {
                            "type": "LLM_JSON_VALIDATION_FAILED",
                            "title": "JSON validation failed after auto repair",
                            "message": str(second_exc),
                            "node_id": node_id,
                            "result": result,
                            "schema_path": str(schema_path),
                        })
                        raise RecoverableValidationError(
                            message=str(second_exc),
                            node_id=node_id,
                            result=result,
                            schema_path=str(schema_path),
                        ) from second_exc
                else:
                    await event_bus.emit(run_id, {
                        "type": "LLM_JSON_VALIDATION_FAILED",
                        "title": "JSON validation failed",
                        "message": original_error,
                        "node_id": node_id,
                        "result": result,
                        "schema_path": str(schema_path),
                    })
                    raise RecoverableValidationError(
                        message=original_error,
                        node_id=node_id,
                        result=result,
                        schema_path=str(schema_path),
                    ) from after_result_exc

        else:
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
