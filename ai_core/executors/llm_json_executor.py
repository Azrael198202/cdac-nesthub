from datetime import datetime, timezone
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
from ai_core.evolution.approval_learning import ApprovalLearningService
from ai_core.context.runtime_context_reducer import RuntimeContextReducer
from ai_core.context.llm_stage_input_slimmer import LLMStageInputSlimmer
from ai_core.roles import RoleProfileSelector, PromptPackLoader, RoleScopedContextReducer
from ai_core.runtime.modeling import ModelStagePolicy
from ai_core.runtime.governance import RuntimeCostPolicy


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
        self.approval_learning = ApprovalLearningService()
        self.context_reducer = RuntimeContextReducer()
        self.input_slimmer = LLMStageInputSlimmer()
        self.role_selector = RoleProfileSelector()
        self.prompt_pack_loader = PromptPackLoader()
        self.role_context_reducer = RoleScopedContextReducer()
        self.stage_policy = ModelStagePolicy()
        self.runtime_cost_policy = RuntimeCostPolicy()

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
        approval_memory = self.approval_learning.build_prompt_reinforcement(
            node_id=node_id,
            user_input=state.get("input", ""),
        )

        role_profile = self.role_selector.select(node_id=node_id, state=state, adapter=adapter).to_dict()
        prompt_pack = self.prompt_pack_loader.load(role_profile.get("role_id", "general_runtime_agent"))
        scoped_context = self.role_context_reducer.reduce_state(
            state=state,
            capability_result=capability_result,
            role_profile=role_profile,
        )
        runtime_context = self._build_runtime_context(state)
        stage_prompt_limit = int(adapter.get("stage_prompt_char_limit") or 0) if isinstance(adapter, dict) else 0
        slim_user_input = self.input_slimmer.slim_user_input(
            node_id=node_id,
            raw_input=state.get("input", ""),
            limit=stage_prompt_limit or None,
        )
        slim_previous_results = self.input_slimmer.slim_previous_results(
            node_id=node_id,
            results=state.get("results", {}),
            limit=stage_prompt_limit or None,
        )
        runtime_context = self.input_slimmer.slim_runtime_context(node_id=node_id, runtime_context=runtime_context)
        runtime_context["role_profile"] = role_profile
        runtime_context["prompt_policy"] = role_profile.get("prompt_policy", {})
        runtime_context["evidence_summary"] = scoped_context.get("evidence_summary")

        await event_bus.emit(run_id, {
            "type": "ROLE_PROFILE_SELECTED",
            "title": "Runtime role profile selected",
            "message": f"role={role_profile.get('role_id')}, policy_tokens={role_profile.get('prompt_policy', {}).get('max_context_tokens')}",
            "node_id": node_id,
            "role_profile": role_profile,
        })

        rendered = self.template.render(prompt.get("user_template", ""), {
            "user_input": slim_user_input,
            "previous_results": slim_previous_results,
            "capability_result": scoped_context.get("capability_result", {}),
            "human_feedback": scoped_context.get("human_feedback", []),
            "correction_memory": correction_memory + ("\n\n" + approval_memory if approval_memory else ""),
            "runtime_context": runtime_context,
            "role_profile": role_profile,
            "prompt_pack": prompt_pack,
            "evidence_summary": scoped_context.get("evidence_summary"),
        })

        pack_system_addendum = prompt_pack.get("system_addendum")
        if pack_system_addendum:
            prompt = {**prompt, "system": (str(prompt.get("system", "")) + "\n\n" + str(pack_system_addendum)).strip()}

        runtime_rules = list(prompt.get("runtime_rules", []) or [])
        runtime_rules.extend(prompt_pack.get("runtime_rules", []) or [])
        if runtime_rules:
            rendered = rendered + "\n\nRole-scoped runtime rules:\n" + "\n".join(f"- {r}" for r in runtime_rules)

        if approval_memory:
            rendered = rendered + "\n\n" + approval_memory
            await event_bus.emit(run_id, {
                "type": "APPROVAL_MEMORY_APPLIED",
                "title": "Approval memory applied",
                "message": f"Applied approved pattern memory for node={node_id}.",
                "node_id": node_id,
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
            "message": f"Rendered prompt length: {len(rendered)} characters; slim_input_length={len(slim_user_input)}",
            "slim_input_length": len(slim_user_input),
            "node_id": node_id,
        })

        role_budget = role_profile.get("prompt_policy", {}).get("max_context_tokens")
        runtime_options = state.get("runtime_options", {}) if isinstance(state.get("runtime_options", {}), dict) else {}
        adapter = {
            **adapter,
            "runtime_role": role_profile.get("role_id"),
            "required_model_capabilities": role_profile.get("required_skills", []),
            "preferred_local_model": runtime_options.get("local_model"),
        }
        if role_budget and not adapter.get("max_prompt_tokens"):
            adapter = {**adapter, "max_prompt_tokens": int(role_budget)}
        adapter = self.runtime_cost_policy.apply_adapter_budget(adapter)

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

        validation_ok = False

        try:
            self.validator.validate_data(result, schema)
            validation_ok = True
            await event_bus.emit(run_id, {
                "type": "LLM_JSON_VALIDATED",
                "title": "JSON validated",
                "message": node_id,
                "node_id": node_id,
            })
        except Exception as exc:
            original_error = str(exc)

            stage_id = self.stage_policy.stage_for(
                node_id=node_id,
                adapter=adapter,
                route_name=adapter.get("route_name") or adapter.get("model_route_name"),
            )
            cost_snapshot = self.runtime_cost_policy.snapshot()
            if (not cost_snapshot.prefer_repair_before_model_escalation) and not adapter.get("force_model_escalation") and self.stage_policy.should_escalate_on_validation_failure(stage_id):
                escalated_adapter = self.stage_policy.escalation_adapter(
                    adapter=adapter,
                    stage_id=stage_id,
                    reason="schema_validation_failed",
                )
                await event_bus.emit(run_id, {
                    "type": "LLM_JSON_VALIDATION_ESCALATING",
                    "title": "Validation failed; escalating model",
                    "message": f"node={node_id}, stage={stage_id}, reason=schema_validation_failed",
                    "node_id": node_id,
                    "stage_id": stage_id,
                    "original_error": original_error,
                })
                escalated_result = await self.router.generate_json(
                    run_id=run_id,
                    node_id=node_id,
                    adapter=escalated_adapter,
                    prompt=prompt,
                    rendered_user_prompt=rendered,
                    schema=schema,
                )
                try:
                    self.validator.validate_data(escalated_result, schema)
                    result = escalated_result
                    validation_ok = True
                    adapter = escalated_adapter
                    await event_bus.emit(run_id, {
                        "type": "LLM_JSON_VALIDATED",
                        "title": "JSON validated after model escalation",
                        "message": node_id,
                        "node_id": node_id,
                        "stage_id": stage_id,
                    })
                except Exception as escalation_exc:
                    result = escalated_result
                    original_error = str(escalation_exc)

            # 1. First repair the RESULT when the model omitted required fields
            # or returned a shape that can be safely normalized.
            if validation_ok:
                result_repaired, repaired_result, result_changes = False, result, []
            else:
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
                    validation_ok = True
                    await event_bus.emit(run_id, {
                        "type": "LLM_JSON_VALIDATED",
                        "title": "JSON validated after result repair",
                        "message": node_id,
                        "node_id": node_id,
                    })
                except Exception as result_repair_exc:
                    result = repaired_result
                    original_error = str(result_repair_exc)

            # 2. Only if result repair did NOT validate, try schema repair.
            if not validation_ok:
                repaired, repaired_schema, changes = self.schema_auto_repair.try_repair(
                    node_id=node_id,
                    schema_path=schema_path,
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
                        validation_ok = True
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
                    cost_snapshot = self.runtime_cost_policy.snapshot()
                    if cost_snapshot.prefer_repair_before_model_escalation and cost_snapshot.allow_paid_model_escalation and not adapter.get("force_model_escalation") and self.stage_policy.should_escalate_on_validation_failure(stage_id):
                        escalated_adapter = self.stage_policy.escalation_adapter(
                            adapter=adapter,
                            stage_id=stage_id,
                            reason="schema_validation_failed_after_repair",
                        )
                        await event_bus.emit(run_id, {
                            "type": "LLM_JSON_VALIDATION_ESCALATING",
                            "title": "Validation failed after repair; escalating model",
                            "message": f"node={node_id}, stage={stage_id}, reason=schema_validation_failed_after_repair",
                            "node_id": node_id,
                            "stage_id": stage_id,
                            "original_error": original_error,
                        })
                        escalated_result = await self.router.generate_json(
                            run_id=run_id,
                            node_id=node_id,
                            adapter=escalated_adapter,
                            prompt=prompt,
                            rendered_user_prompt=rendered,
                            schema=schema,
                        )
                        try:
                            self.validator.validate_data(escalated_result, schema)
                            result = escalated_result
                            validation_ok = True
                            adapter = escalated_adapter
                            await event_bus.emit(run_id, {
                                "type": "LLM_JSON_VALIDATED",
                                "title": "JSON validated after post-repair escalation",
                                "message": node_id,
                                "node_id": node_id,
                                "stage_id": stage_id,
                            })
                        except Exception as escalation_exc:
                            result = escalated_result
                            original_error = str(escalation_exc)
                    if not validation_ok:
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
                        ) from exc

        if not validation_ok:
            raise RecoverableValidationError(
                message="JSON validation did not complete.",
                node_id=node_id,
                result=result,
                schema_path=str(schema_path),
            )

        result["_executor_type"] = "llm_json"
        result["_node_id"] = node_id
        result["_adapter_id"] = adapter.get("adapter_id")
        return result
    def _build_runtime_context(self, state: dict) -> dict:
        """Build generic runtime context for prompts.

        This is intentionally domain-neutral. It gives runtime-generated nodes
        enough context to resolve relative expressions already present in the
        user input, without hardcoding any business vocabulary in ai_core.
        """
        now = datetime.now(timezone.utc)
        return {
            "current_datetime_utc": now.isoformat(),
            "current_date_utc": now.date().isoformat(),
            "timezone_hint": state.get("timezone") or state.get("timezone_hint") or "system_default",
            "locale_hint": state.get("locale") or state.get("locale_hint") or "auto",
        }

