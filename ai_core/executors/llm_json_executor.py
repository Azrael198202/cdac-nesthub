from datetime import datetime, timezone
import json
from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import PROJECT_ROOT
from ai_core.executors.template_engine import TemplateEngine
from ai_core.validation.schema_validator import SchemaValidator
from ai_core.llm.provider_router import ProviderRouter
from ai_core.events.event_bus import event_bus
from ai_core.validation.recoverable_validation_error import RecoverableValidationError
from ai_core.workflow.workflow_contract_builder import WorkflowContractBuilder
from ai_core.workflow.execution_options import ACTION_TO_METHOD, fixed_options_for_prompt
from ai_core.validation.schema_auto_repair import SchemaAutoRepair
from ai_core.validation.result_auto_repair import ResultAutoRepair
from ai_core.evolution.runtime_learning import RuntimeLearningService
from ai_core.evolution.approval_learning import ApprovalLearningService
from ai_core.context.runtime_context_reducer import RuntimeContextReducer
from ai_core.context.llm_stage_input_slimmer import LLMStageInputSlimmer
from ai_core.roles import RoleProfileSelector, PromptPackLoader, RoleScopedContextReducer
from ai_core.runtime.modeling import ModelStagePolicy
from ai_core.runtime.governance import RuntimeCostPolicy
from ai_core.llm.prompt_io_recorder import PromptIORecorder


class LLMJsonExecutor:
    """
    Runtime-configured LLM JSON executor.

    No business/domain/task logic is allowed here.
    """

    def __init__(self) -> None:
        self.loader = ConfigLoader()
        self.template = TemplateEngine()
        self.validator = SchemaValidator()
        self.workflow_contract_builder = WorkflowContractBuilder()
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
        self.prompt_io_recorder = PromptIORecorder()

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
        # input_parsing must remain a small, generic JSON extraction stage.
        # Role-specific packs are useful later, but they can add irrelevant
        # behavioral text (for example writer/retrieval rules) and destabilize
        # local JSON output. Keep only date/time normalization context here.
        if node_id == "input_parsing":
            role_profile = {
                "role_id": "generic_input_parser",
                "role_type": "input_parsing",
                "required_skills": ["extract_runtime_parameters"],
                "prompt_policy": {
                    "max_context_tokens": 1200,
                    "include_full_trace": False,
                    "include_only_evidence_summary": False,
                    "max_previous_result_items": 0,
                    "max_evidence_items": 0,
                    "max_chars_per_evidence": 0,
                },
            }
            prompt_pack = {}
        else:
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
        if node_id not in {"input_parsing", "intent_recognition", "workflow_planning"}:
            runtime_context["role_profile"] = {
                "role_id": role_profile.get("role_id"),
                "role_type": role_profile.get("role_type"),
            }
            summary = scoped_context.get("evidence_summary")
            if isinstance(summary, dict):
                runtime_context["evidence_summary"] = {
                    "known_parameters": summary.get("known_parameters", {}),
                    "selected_evidence": (summary.get("selected_evidence") or [])[:2],
                }

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

        prompt_trace_path = self.prompt_io_recorder.record(
            run_id=run_id,
            node_id=node_id,
            phase="prompt_rendered",
            payload={
                "run_id": run_id,
                "node_id": node_id,
                "adapter_id": adapter.get("adapter_id"),
                "prompt_id": prompt.get("id"),
                "system_prompt": prompt.get("system"),
                "user_prompt": rendered,
                "slim_user_input": slim_user_input,
                "slim_previous_results": slim_previous_results,
                "runtime_context": runtime_context,
                "schema_path": str(schema_path),
                "schema": schema,
            },
        )

        await event_bus.emit(run_id, {
            "type": "LLM_PROMPT_RENDERED",
            "title": "Prompt rendered",
            "message": f"Rendered prompt length: {len(rendered)} characters; slim_input_length={len(slim_user_input)}; trace={prompt_trace_path}",
            "slim_input_length": len(slim_user_input),
            "prompt_trace_path": prompt_trace_path,
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

        try:
            result = await self.router.generate_json(
                run_id=run_id,
                node_id=node_id,
                adapter=adapter,
                prompt=prompt,
                rendered_user_prompt=rendered,
                schema=schema,
            )
            output_trace_path = self.prompt_io_recorder.record(
                run_id=run_id,
                node_id=node_id,
                phase="llm_output",
                payload={
                    "run_id": run_id,
                    "node_id": node_id,
                    "adapter_id": adapter.get("adapter_id"),
                    "prompt_id": prompt.get("id"),
                    "result": result,
                },
            )
            await event_bus.emit(run_id, {
                "type": "LLM_OUTPUT_RECORDED",
                "title": "LLM output recorded",
                "message": f"LLM output trace={output_trace_path}",
                "node_id": node_id,
                "output_trace_path": output_trace_path,
            })
        except Exception as exc:
            recovered = self._recover_stage_result_after_provider_error(
                node_id=node_id,
                state=state,
                slim_user_input=slim_user_input,
                slim_previous_results=slim_previous_results,
                error=str(exc),
            )
            if recovered is not None:
                result = recovered
                output_trace_path = self.prompt_io_recorder.record(
                    run_id=run_id,
                    node_id=node_id,
                    phase="llm_output_recovered",
                    payload={
                        "run_id": run_id,
                        "node_id": node_id,
                        "adapter_id": adapter.get("adapter_id"),
                        "prompt_id": prompt.get("id"),
                        "provider_error": str(exc),
                        "result": result,
                    },
                )
                await event_bus.emit(run_id, {
                    "type": "LLM_OUTPUT_RECOVERED",
                    "title": "LLM stage recovered from provider error",
                    "message": f"node={node_id}; trace={output_trace_path}",
                    "node_id": node_id,
                    "output_trace_path": output_trace_path,
                })
            else:
                error_trace_path = self.prompt_io_recorder.record(
                    run_id=run_id,
                    node_id=node_id,
                    phase="llm_error",
                    payload={
                        "run_id": run_id,
                        "node_id": node_id,
                        "adapter_id": adapter.get("adapter_id"),
                        "prompt_id": prompt.get("id"),
                        "error": str(exc),
                        "system_prompt": prompt.get("system"),
                        "user_prompt": rendered,
                        "schema": schema,
                    },
                )
                await event_bus.emit(run_id, {
                    "type": "LLM_ERROR_RECORDED",
                    "title": "LLM error recorded",
                    "message": f"LLM error trace={error_trace_path}",
                    "node_id": node_id,
                    "error_trace_path": error_trace_path,
                })
                raise

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

        result = self._postprocess_stage_result(node_id=node_id, result=result, state=state, slim_user_input=slim_user_input)
        result["_executor_type"] = "llm_json"
        result["_node_id"] = node_id
        result["_adapter_id"] = adapter.get("adapter_id")
        return result

    def _postprocess_stage_result(self, *, node_id: str | None, result: dict, state: dict, slim_user_input: str) -> dict:
        node = str(node_id or "")
        if node == "workflow_planning":
            return self._ensure_executable_workflow(result=result, state=state, slim_user_input=slim_user_input)
        if node == "intent_recognition":
            return self._ensure_intent_carry_forward(result=result, state=state)
        if node == "input_parsing":
            return self._ensure_input_carry_forward(result=result, state=state, slim_user_input=slim_user_input)
        return result

    def _ensure_input_carry_forward(self, *, result: dict, state: dict, slim_user_input: str) -> dict:
        if not isinstance(result, dict):
            result = {}
        payload = self._loads_json_obj(str(state.get("input") or "")) or self._loads_json_obj(slim_user_input) or {}
        context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
        agent_params = context.get("agent_parameters") if isinstance(context.get("agent_parameters"), dict) else payload.get("agent_parameters")
        values = agent_params.get("values") if isinstance(agent_params, dict) and isinstance(agent_params.get("values"), dict) else {}
        parsed = result.get("parsed_entities") if isinstance(result.get("parsed_entities"), dict) else {}
        for k, v in values.items():
            if v not in (None, "", [], {}):
                parsed.setdefault(str(k), v)
        if payload.get("objective") not in (None, ""):
            parsed.setdefault("objective", payload.get("objective"))
        result["parsed_entities"] = parsed
        result.setdefault("original_input", str(payload.get("objective") or payload.get("instruction") or state.get("input") or "")[:1000])
        result.setdefault("missing_information", [])
        return result

    def _ensure_intent_carry_forward(self, *, result: dict, state: dict) -> dict:
        if not isinstance(result, dict):
            result = {}
        parsed = (state.get("results") or {}).get("input_parsing") if isinstance(state.get("results"), dict) else {}
        if isinstance(parsed, dict):
            entities = parsed.get("parsed_entities") if isinstance(parsed.get("parsed_entities"), dict) else {}
            result.setdefault("normalized_intent", {})
            if isinstance(result["normalized_intent"], dict):
                for k, v in entities.items():
                    if v not in (None, "", [], {}):
                        result["normalized_intent"].setdefault(str(k), v)
        result.setdefault("missing_information", [])
        return result

    FIXED_EXECUTION_ACTIONS = dict(ACTION_TO_METHOD)

    def _action_type_from_text(self, value: object, default: str = "") -> str:
        """Return only an explicit fixed action type.

        Workflow planning must ask the LLM to rank the fixed execution options
        and choose one. Runtime normalization must not guess from verbs such as
        fetch/search/generate, because that lets later stages silently change
        the workflow intent.
        """
        text = str(value or "").strip().lower()
        return text if text in self.FIXED_EXECUTION_ACTIONS else default

    def _execution_decision_from_plan(self, container: dict) -> dict:
        if not isinstance(container, dict):
            return {}
        for key in ("execution_decision", "execution_method_decision", "method_decision"):
            value = container.get(key)
            if isinstance(value, dict):
                return value
        options = container.get("execution_options") or container.get("method_options") or container.get("candidate_actions")
        if isinstance(options, list) and options:
            normalized = []
            for item in options:
                if not isinstance(item, dict):
                    continue
                at = self._action_type_from_text(item.get("action_type") or item.get("execution_action") or item.get("id") or item.get("name"))
                if at:
                    normalized.append({**item, "action_type": at})
            if normalized:
                normalized.sort(key=lambda x: int(x.get("priority") or x.get("rank") or 999))
                top = normalized[0]
                return {"selected_action_type": top.get("action_type"), "ranked_options": normalized}
        return {}

    def _selected_action_type(self, *containers: dict) -> str:
        for container in containers:
            decision = self._execution_decision_from_plan(container)
            action_type = self._action_type_from_text(
                decision.get("selected_action_type") or decision.get("action_type") or decision.get("selected_option")
            )
            if action_type:
                return action_type
            action_type = self._action_type_from_text(container.get("action_type") or container.get("execution_action")) if isinstance(container, dict) else ""
            if action_type:
                return action_type
        return ""

    def _method_from_action_type(self, action_type: str) -> str:
        return self.FIXED_EXECUTION_ACTIONS.get(str(action_type or ""), "content_generation")

    def _steps_from_execution_plan_action(self, *, result: dict, state: dict) -> list[dict]:
        execution_plan = result.get("execution_plan") if isinstance(result.get("execution_plan"), dict) else {}
        action = execution_plan.get("action") or result.get("action")
        if not action:
            return []
        action_type = self._selected_action_type(execution_plan, result)
        if not action_type:
            return []
        params = execution_plan.get("parameters") if isinstance(execution_plan.get("parameters"), dict) else {}
        next_steps = execution_plan.get("next_steps") if isinstance(execution_plan.get("next_steps"), list) else []
        intent = (state.get("results") or {}).get("intent_recognition") if isinstance(state.get("results"), dict) else {}
        objective = str(result.get("objective") or execution_plan.get("objective") or result.get("message") or intent.get("intent_summary") or state.get("input") or "")[:800]
        method = self._method_from_action_type(action_type)
        step = {
            "step_id": str(execution_plan.get("step_id") or "step_1"),
            "task_id": str(execution_plan.get("task_id") or "step_1"),
            "step_type": "runtime_execution",
            "action": str(action),
            "action_type": action_type,
            "execution_action": action_type,
            "objective": objective,
            "parameters": {"known": params, "missing_required": {}, "optional": {}},
            "required_capability": str(result.get("_node_id") or result.get("required_capability") or self._generic_capability_from_state(state)),
            "execution_method": method,
            "execution_method_policy": {"preferred_methods": [method], "disabled_methods": [m for m in ["web_search", "api_call", "content_generation", "runtime_generated_tool", "existing_tool", "knowledge_base", "shell"] if m != method], "fallback_allowed": False},
            "execution_strategy": [method],
            "source_policy": {"allow_external": method in {"api_call", "web_search"}, "allow_internal": True, "requires_live_evidence": method in {"api_call", "web_search"}},
            "execution_ready": True,
            "depends_on": [],
            "requires_human_confirmation": False,
            "missing_fields": [],
        }
        if next_steps:
            step["validation_actions"] = next_steps
        return [step]

    def _ensure_executable_workflow(self, *, result: dict, state: dict, slim_user_input: str) -> dict:
        # v5.0: workflow_planning is the single owner of execution-method
        # decision. The model is prompted to rank fixed execution options, and
        # this structural normalizer guarantees a locked workflow contract even
        # when the raw model output is incomplete. It does not run tools or
        # choose business-specific providers.
        return self.workflow_contract_builder.normalize_workflow_result(
            result=result if isinstance(result, dict) else {},
            state=state,
            slim_user_input=slim_user_input,
        )

    def _generic_locked_step_from_state(self, *, state: dict, slim_user_input: str) -> dict:
        results = state.get("results") if isinstance(state.get("results"), dict) else {}
        context_record = results.get("context_awareness") if isinstance(results.get("context_awareness"), dict) else {}
        context_payload = context_record.get("context_record") if isinstance(context_record.get("context_record"), dict) else context_record
        clean_context = context_payload.get("clean_context") if isinstance(context_payload.get("clean_context"), dict) else {}
        requirement_record = results.get("requirement_completion") if isinstance(results.get("requirement_completion"), dict) else {}
        requirement_payload = requirement_record.get("requirement_record") if isinstance(requirement_record.get("requirement_record"), dict) else requirement_record
        intent = results.get("intent_recognition") if isinstance(results.get("intent_recognition"), dict) else {}
        parsed = results.get("input_parsing") if isinstance(results.get("input_parsing"), dict) else {}
        known = {}
        for source in (
            clean_context.get("known_parameters"),
            requirement_payload.get("known_parameters"),
            intent.get("normalized_intent") if isinstance(intent.get("normalized_intent"), dict) else {},
            parsed.get("parsed_entities") if isinstance(parsed.get("parsed_entities"), dict) else {},
        ):
            if isinstance(source, dict):
                for k, v in source.items():
                    if v not in (None, "", [], {}):
                        known[str(k)] = v
        objective = str(
            clean_context.get("intent_summary")
            or intent.get("intent_summary")
            or intent.get("objective")
            or parsed.get("original_input")
            or state.get("input")
            or slim_user_input
            or "execute requested task"
        )[:800]
        capability = str(clean_context.get("recognized_intent") or intent.get("intent_type") or intent.get("classified_intent") or "generic_content_generation")[:120]
        # Preserve the upstream LLM execution decision. Structural repair may
        # create missing planned_steps, but it must not change the selected
        # execution action. This keeps workflow_planning as the single place
        # where the fixed action options are ranked and selected.
        selected_action = self._selected_action_type(intent, clean_context, requirement_payload, parsed) or "call_llm"
        decision_source = self._execution_decision_from_plan(intent) or self._execution_decision_from_plan(clean_context) or {}
        raw_ranked = decision_source.get("ranked_options") if isinstance(decision_source.get("ranked_options"), list) else []
        ranked_options = []
        seen_actions = set()
        for index, item in enumerate(raw_ranked):
            if not isinstance(item, dict):
                continue
            action = self._action_type_from_text(item.get("action_type") or item.get("selected_action_type") or item.get("id") or item.get("name"))
            if not action or action in seen_actions:
                continue
            seen_actions.add(action)
            ranked_options.append({**item, "action_type": action, "priority": int(item.get("priority") or item.get("rank") or index + 1)})
        for action in self.FIXED_EXECUTION_ACTIONS:
            if action not in seen_actions:
                ranked_options.append({"action_type": action, "priority": len(ranked_options) + 1, "reason": "available fixed execution option"})
                seen_actions.add(action)
        ranked_options.sort(key=lambda x: int(x.get("priority") or 999))
        selected_method = self._method_from_action_type(selected_action)
        return {
            "step_id": "step_1",
            "task_id": "step_1",
            "step_type": "runtime_execution",
            "action": "execute_with_selected_fixed_action",
            "action_type": selected_action,
            "execution_action": selected_action,
            "objective": objective,
            "input_from": ["input_parsing", "intent_recognition", "requirement_completion", "context_awareness"],
            "parameters": {"known": known, "missing_required": {}, "optional": {"original_input": str(state.get("input") or slim_user_input)}},
            "required_capability": capability,
            "execution_decision": {"selected_action_type": selected_action, "ranked_options": ranked_options, "selection_rules": ["no-key options before key-required options", "free options before paid options", "prepared resources before unprepared resources", "locked workflow before executor fallback"]},
            "execution_method": selected_method,
            "execution_method_policy": {"preferred_methods": [selected_method], "disabled_methods": [m for m in ["web_search", "api_call", "content_generation", "runtime_generated_tool", "shell", "existing_tool", "knowledge_base"] if m != selected_method], "fallback_allowed": False},
            "execution_strategy": [selected_method],
            "source_policy": {"allow_external": selected_method in {"api_call", "web_search"}, "allow_internal": True, "requires_live_evidence": selected_method in {"api_call", "web_search"}},
            "execution_ready": True,
            "depends_on": [],
            "requires_human_confirmation": False,
            "missing_fields": [],
        }

    def _normalize_generated_step(self, step: dict, index: int, state: dict) -> dict:
        out = dict(step)
        step_id = str(out.get("step_id") or out.get("task_id") or f"step_{index + 1}")
        out["step_id"] = step_id
        out.setdefault("task_id", step_id)
        out.setdefault("depends_on", [])
        out.setdefault("requires_human_confirmation", False)
        params = out.get("parameters") if isinstance(out.get("parameters"), dict) else {}
        if not any(k in params for k in ("known", "missing_required", "optional")):
            params = {"known": params, "missing_required": {}, "optional": {}}
        else:
            params = {
                "known": params.get("known") if isinstance(params.get("known"), dict) else {},
                "missing_required": params.get("missing_required") if isinstance(params.get("missing_required"), (dict, list)) else {},
                "optional": params.get("optional") if isinstance(params.get("optional"), dict) else {},
            }
        out["parameters"] = params
        out.setdefault("required_capability", self._generic_capability_from_state(state))
        action_type = self._selected_action_type(out)
        if not action_type:
            out["execution_ready"] = False
            out.setdefault("missing_fields", [])
            out["missing_fields"] = list(dict.fromkeys([*out.get("missing_fields", []), "execution_decision.selected_action_type"]))
            action_type = "no_op"
        method = self._method_from_action_type(action_type)
        out["action_type"] = action_type
        out["execution_action"] = action_type
        out["execution_method"] = method
        out["execution_method_policy"] = {"preferred_methods": [method], "disabled_methods": [m for m in ["web_search", "api_call", "content_generation", "runtime_generated_tool", "existing_tool", "knowledge_base", "shell"] if m != method], "fallback_allowed": False}
        out["execution_strategy"] = [method]
        out.setdefault("execution_ready", not bool(params.get("missing_required")))
        out["source_policy"] = out.get("source_policy") if isinstance(out.get("source_policy"), dict) else {}
        out["source_policy"].setdefault("allow_external", method in {"api_call", "web_search"})
        out["source_policy"].setdefault("allow_internal", True)
        out["source_policy"].setdefault("requires_live_evidence", method in {"api_call", "web_search"})
        return out

    def _build_agent_graph(self, steps: list[dict]) -> dict:
        nodes = []
        edges = []
        for step in steps:
            step_id = str(step.get("step_id"))
            nodes.append({
                "id": step_id,
                "relation": "dependent" if step.get("depends_on") else "independent",
                "execution_method": step.get("execution_method"),
            })
            for dep in step.get("depends_on") or []:
                edges.append({"from": str(dep), "to": step_id, "context_policy": "strict_json_safe_summary"})
        return {"main_graph": {"nodes": nodes, "edges": edges}, "subgraphs": []}

    def _generic_capability_from_state(self, state: dict) -> str:
        results = state.get("results") if isinstance(state.get("results"), dict) else {}
        intent = results.get("intent_recognition") if isinstance(results.get("intent_recognition"), dict) else {}
        for key in ("intent_type", "classified_intent", "intent", "name"):
            value = intent.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return "generic_content_generation"

    def _recover_stage_result_after_provider_error(self, *, node_id: str | None, state: dict, slim_user_input: str, slim_previous_results: dict, error: str) -> dict | None:
        """Generic last-resort recovery for local JSON stage failures.

        This does not replace the LLM stage. It runs only after provider timeout
        or malformed JSON. The recovered object is deliberately minimal and
        schema-shaped so LangGraph can continue instead of looping on the same
        heavy prompt. It contains no domain-specific keywords.
        """
        node = str(node_id or "")
        if node == "input_parsing":
            return self._recover_input_parsing(state=state, slim_user_input=slim_user_input, error=error)
        if node == "workflow_planning":
            return self._recover_workflow_planning(state=state, slim_user_input=slim_user_input, slim_previous_results=slim_previous_results, error=error)
        return None

    def _recover_input_parsing(self, *, state: dict, slim_user_input: str, error: str) -> dict:
        payload = self._loads_json_obj(slim_user_input) or self._loads_json_obj(str(state.get("input") or "")) or {}
        context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
        agent_parameters = context.get("agent_parameters") if isinstance(context.get("agent_parameters"), dict) else payload.get("agent_parameters")
        values = agent_parameters.get("values") if isinstance(agent_parameters, dict) and isinstance(agent_parameters.get("values"), dict) else {}
        missing = agent_parameters.get("missing") if isinstance(agent_parameters, dict) and isinstance(agent_parameters.get("missing"), list) else []
        parsed_entities = {
            k: v for k, v in {
                "request_type": payload.get("request_type"),
                "task_name": payload.get("task_name"),
                "participant_name": payload.get("participant_name"),
                "objective": payload.get("objective"),
                "parameters": values,
            }.items() if v not in (None, "", [], {})
        }
        return {
            "language": "unknown",
            "original_input": str(payload.get("objective") or payload.get("instruction") or slim_user_input)[:300],
            "parsed_entities": parsed_entities,
            "semantic_modifiers": [],
            "constraints": {},
            "temporal_expressions": [],
            "missing_information": [str(x.get("name") or x) for x in missing if str(x.get("name") if isinstance(x, dict) else x).strip()],
            "safety_notes": [],
            "recovery": {"status": "provider_error_recovered", "reason": error[:500]},
        }

    def _recover_workflow_planning(self, *, state: dict, slim_user_input: str, slim_previous_results: dict, error: str) -> dict:
        payload = self._loads_json_obj(slim_user_input) or {}
        previous = slim_previous_results if isinstance(slim_previous_results, dict) else {}
        intent = previous.get("intent_recognition") if isinstance(previous.get("intent_recognition"), dict) else {}
        parsed = previous.get("input_parsing") if isinstance(previous.get("input_parsing"), dict) else {}
        normalized = intent.get("normalized_intent") if isinstance(intent.get("normalized_intent"), dict) else {}
        parsed_entities = parsed.get("parsed_entities") if isinstance(parsed.get("parsed_entities"), dict) else {}
        known = {}
        for source in (normalized, parsed_entities, payload.get("agent_parameters", {}).get("values") if isinstance(payload.get("agent_parameters"), dict) else {}):
            if isinstance(source, dict):
                for k, v in source.items():
                    if v not in (None, "", [], {}):
                        known[str(k)] = v
        objective = str(payload.get("objective") or intent.get("intent_summary") or parsed.get("original_input") or state.get("input") or "execute requested task")[:500]
        capability = str(intent.get("intent_type") or intent.get("classified_intent") or "generic_content_generation")[:120]
        selected_action = self._selected_action_type(intent) or "call_llm"
        selected_method = self._method_from_action_type(selected_action)
        step = {
            "step_id": "step_1",
            "task_id": "step_1",
            "step_type": "runtime_execution",
            "objective": objective,
            "input_from": ["input_parsing", "intent_recognition", "requirement_completion", "context_awareness"],
            "parameters": {"known": known, "missing_required": {}, "optional": {}},
            "required_capability": capability,
            "action_type": selected_action,
            "execution_decision": {"selected_action_type": selected_action, "ranked_options": [{"action_type": selected_action, "priority": 1, "reason": "recovery uses upstream selected fixed action when available"}]},
            "execution_method": selected_method,
            "execution_method_policy": {"preferred_methods": [selected_method], "fallback_allowed": False},
            "execution_strategy": [selected_method],
            "source_policy": {"allow_external": selected_method in {"api_call", "web_search"}, "allow_internal": True, "requires_live_evidence": selected_method in {"api_call", "web_search"}},
            "execution_ready": True,
            "human_interaction": {},
            "next_action": "execute",
            "depends_on": [],
            "requires_human_confirmation": False,
            "missing_fields": [],
        }
        return {
            "workflow": {"workflow_id": "runtime_generated_workflow", "status": "ready"},
            "agent_graph": {"main_graph": {"nodes": [{"id": "step_1", "relation": "independent", "execution_method": selected_method}], "edges": []}, "subgraphs": []},
            "planned_steps": [step],
            "execution_plan": {"steps": [step], "locked": True},
            "blocking_missing_information": [],
            "required_capabilities": [capability],
            "execution_strategy": [selected_method],
            "human_interaction": {},
            "recovery": {"status": "provider_error_recovered", "reason": error[:500]},
        }

    def _loads_json_obj(self, text: str) -> dict:
        try:
            value = json.loads(str(text or ""))
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

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

