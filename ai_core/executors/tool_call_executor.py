from __future__ import annotations

from typing import Any

from ai_core.events.event_bus import event_bus
from ai_core.runtime.provenance import ExecutionProvenanceRecorder
from ai_core.tools.runtime_tool_registry import RuntimeToolRegistry
from ai_core.modules.module_builder import RuntimeModuleBuilder
from ai_core.modules.module_loader import RuntimeModuleLoader
from ai_core.modules.module_artifact_generator import RuntimeModuleArtifactGenerator
from ai_core.modules.runtime_generated_module_installer import RuntimeGeneratedModuleInstaller
from ai_core.workflow.workflow_normalizer import WorkflowNormalizer
from ai_core.tools.generic_tool_runner import GenericToolRunner
from ai_core.tools.runtime_tool_artifact_generator import RuntimeToolArtifactGenerator
from ai_core.tools.runtime_generated_tool_installer import RuntimeGeneratedToolInstaller
from ai_core.research.api_discovery import ApiDiscoveryEngine


class ToolCallExecutor:
    """
    Generic tool-call executor.

    It does not know any business/domain-specific concepts. It reads the
    runtime-generated workflow plan, normalizes generic fields, resolves tool
    availability by capability metadata, and returns a continuation-aware
    execution state.
    """

    def __init__(self) -> None:
        self.tool_registry = RuntimeToolRegistry()
        self.module_builder = RuntimeModuleBuilder()
        self.module_loader = RuntimeModuleLoader()
        self.module_artifact_generator = RuntimeModuleArtifactGenerator()
        self.module_installer = RuntimeGeneratedModuleInstaller()
        self.normalizer = WorkflowNormalizer()
        self.tool_runner = GenericToolRunner()
        self.artifact_generator = RuntimeToolArtifactGenerator()
        self.artifact_installer = RuntimeGeneratedToolInstaller()
        self.provenance = ExecutionProvenanceRecorder()
        self.api_discovery = ApiDiscoveryEngine()

    async def execute(
        self,
        workflow_node: dict[str, Any],
        node_config: dict[str, Any],
        state: dict[str, Any],
        capability_result: dict[str, Any],
    ) -> dict[str, Any]:
        return await self.run(
            run_id=state.get("run_id", ""),
            node_id=node_config.get("node_id") or workflow_node.get("id", "execution"),
            node_config=node_config,
            state=state,
            capability_result=capability_result,
        )

    async def run(
        self,
        *,
        run_id: str,
        node_id: str,
        node_config: dict[str, Any],
        state: dict[str, Any],
        capability_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        previous_results = state.get("results", {})
        workflow_plan = previous_results.get("workflow_planning", {})
        normalized_plan = self.normalizer.normalize(workflow_plan)
        previous_results["workflow_planning"] = normalized_plan
        planned_steps = normalized_plan.get("planned_steps", [])

        await event_bus.emit(run_id, {
            "type": "EXECUTION_PLANNER_STARTED",
            "title": "Execution planner started",
            "message": f"Planning execution for {len(planned_steps)} step(s).",
            "node_id": node_id,
        })

        if not planned_steps:
            return {
                "_executor_type": "tool_call",
                "_node_id": node_id,
                "status": "no_planned_steps",
                "message": "No planned_steps found in workflow_planning result.",
                "execution_steps": [],
                "blocked_steps": [],
                "human_interactions": [],
                "missing_tools": [],
                "safety_holds": [],
                "normalized_workflow": normalized_plan,
            }

        execution_steps: list[dict[str, Any]] = []
        blocked_steps: list[dict[str, Any]] = []
        human_interactions: list[dict[str, Any]] = []
        missing_tools: list[dict[str, Any]] = []
        safety_holds: list[dict[str, Any]] = []
        generated_modules: list[dict[str, Any]] = []

        for index, step in enumerate(planned_steps):
            step_id = str(step.get("step_id") or step.get("task_id") or f"step_{index + 1}")
            required_capability = self._capability_name(step.get("required_capability"))
            human_interaction = self._normalize_human_interaction(step.get("human_interaction"))
            execution_ready = bool(step.get("execution_ready", False))
            requires_confirmation = bool(step.get("requires_human_confirmation", False))

            await event_bus.emit(run_id, {
                "type": "EXECUTION_STEP_ANALYZING",
                "title": "Analyzing execution step",
                "message": f"{step_id} / capability={required_capability or 'none'}",
                "node_id": node_id,
                "step_id": step_id,
            })

            explicit_interaction_required = bool(human_interaction.get("required"))
            missing_fields = self._missing_fields(step)

            if explicit_interaction_required or missing_fields:
                interaction = {
                    "step_id": step_id,
                    "type": human_interaction.get("type") or "collect_missing_information",
                    "objective": step.get("objective"),
                    "fields": human_interaction.get("fields") or missing_fields,
                    "reason": "Required information is missing or human interaction is required.",
                    "source_step": step,
                }
                human_interactions.append(interaction)
                blocked_steps.append({
                    "step_id": step_id,
                    "status": "missing_required_information" if missing_fields else "waiting_for_human_interaction",
                    "missing_fields": missing_fields,
                    "reason": interaction["reason"],
                    "source_step": step,
                })
                continue

            if not execution_ready:
                blocked_steps.append({
                    "step_id": step_id,
                    "status": "not_execution_ready",
                    "reason": "execution_ready is false.",
                    "source_step": step,
                })
                continue

            tool = self.tool_registry.find_by_capability(required_capability) if required_capability else None
            if not tool and required_capability:
                existing_module = self.module_loader.load_by_capability(required_capability)
                if existing_module is not None:
                    module_input = self._build_tool_input(
                        step=step,
                        run_id=run_id,
                        node_id=node_id,
                        step_id=step_id,
                        user_input=state.get("input", ""),
                    )
                    await event_bus.emit(run_id, {
                        "type": "MODULE_EXECUTION_STARTED",
                        "title": "Runtime module execution started",
                        "message": f"Executing reusable module for capability={required_capability}",
                        "node_id": node_id,
                        "step_id": step_id,
                    })
                    module_record = self.module_loader.registry.find_by_capability(required_capability) or {"module_id": required_capability}
                    trace = self.provenance.start(
                        run_id=run_id,
                        node_id=node_id,
                        step_id=step_id,
                        component_type="runtime_module",
                        component_id=str(module_record.get("module_id") or required_capability),
                        capability=required_capability,
                        input_data=module_input,
                        artifact=module_record,
                    )
                    try:
                        raw_module_result = existing_module.run(module_input)
                        module_result = self._normalize_runtime_execution_result(raw_module_result, source="runtime_module")
                        trace = self.provenance.finish(
                            trace,
                            output=module_result,
                            status="success" if self._is_success_result(module_result) else "error",
                            error=module_result.get("error") if isinstance(module_result, dict) else None,
                        )
                        module_result = self.provenance.attach(module_result, trace)
                    except Exception as exc:
                        module_result = {"status": "error", "error": {"message": str(exc)}, "data": {}, "source": "runtime_module"}
                        trace = self.provenance.finish(trace, output=module_result, status="error", error=module_result.get("error"))
                        module_result = self.provenance.attach(module_result, trace)
                    if isinstance(module_result, dict) and module_result.get("provenance"):
                        await event_bus.emit(run_id, {
                            "type": "EXECUTION_PROVENANCE_RECORDED",
                            "title": "Execution provenance recorded",
                            "message": f"Recorded provenance for step={step_id}",
                            "node_id": node_id,
                            "step_id": step_id,
                            "result": module_result.get("provenance"),
                        })
                    execution_steps.append({
                        "step_id": step_id,
                        "status": "executed" if self._is_success_result(module_result) else "module_execution_failed",
                        "module": {"capability": required_capability},
                        "input": module_input,
                        "result": module_result,
                        "provenance": module_result.get("provenance") if isinstance(module_result, dict) else None,
                        "source_step": step,
                    })
                    if not self._is_success_result(module_result):
                        blocked_steps.append({
                            "step_id": step_id,
                            "status": "module_execution_failed",
                            "reason": self._result_error_message(module_result, "Module execution failed."),
                            "source_step": step,
                            "module_result": module_result,
                        })
                    continue

            if not tool:
                generated_spec = self.tool_registry.create_missing_tool_spec(
                    capability=required_capability or "unknown_capability",
                    step=step,
                    user_input=state.get("input", ""),
                )

                if self._has_executable_implementation(generated_spec):
                    tool = generated_spec
                    await event_bus.emit(run_id, {
                        "type": "RUNTIME_TOOL_GENERATED_AND_REGISTERED",
                        "title": "Runtime tool generated and registered",
                        "message": f"Generated executable runtime tool for capability={required_capability or 'unknown_capability'}",
                        "node_id": node_id,
                        "step_id": step_id,
                        "result": self._public_tool_spec(generated_spec),
                    })
                else:
                    generated_tool = await self._try_generate_executable_tool(
                        run_id=run_id,
                        node_id=node_id,
                        step_id=step_id,
                        capability=required_capability or "unknown_capability",
                        step=step,
                        state=state,
                    )
                    if generated_tool:
                        tool = generated_tool
                    else:
                        module_result = await self._try_generate_executable_module(
                            run_id=run_id,
                            node_id=node_id,
                            step_id=step_id,
                            capability=required_capability or "unknown_capability",
                            step=step,
                            state=state,
                        )
                        if module_result and module_result.get("module"):
                            generated_modules.append({
                                "step_id": step_id,
                                "capability": required_capability,
                                "generated_module": module_result.get("registry_record"),
                            })
                            module_input = self._build_tool_input(
                                step=step, run_id=run_id, node_id=node_id, step_id=step_id, user_input=state.get("input", "")
                            )
                            normalized_module_result = self._normalize_runtime_execution_result(
                                module_result.get("result"), source="runtime_generated_module"
                            )
                            execution_steps.append({
                                "step_id": step_id,
                                "status": "executed" if self._is_success_result(normalized_module_result) else "module_execution_failed",
                                "module": module_result.get("registry_record"),
                                "input": module_input,
                                "result": normalized_module_result,
                                "provenance": normalized_module_result.get("provenance") if isinstance(normalized_module_result, dict) else None,
                                "source_step": step,
                            })
                            if not self._is_success_result(normalized_module_result):
                                blocked_steps.append({
                                    "step_id": step_id,
                                    "status": "module_execution_failed",
                                    "capability": required_capability,
                                    "reason": self._result_error_message(normalized_module_result, "Module execution failed."),
                                    "source_step": step,
                                    "module_result": normalized_module_result,
                                })
                            continue

                        module_blueprint = self.module_builder.ensure_module_for_capability(
                            capability=required_capability or "unknown_capability",
                            source_step=step,
                            user_input=state.get("input", ""),
                        )
                        generated_modules.append({"step_id": step_id, "capability": required_capability, "generated_module": module_blueprint})

                        # v50: if a reusable module is already registered, the workflow must
                        # immediately re-enter execution instead of pausing on a stale
                        # missing_tool_implementation state. ai_core remains generic here:
                        # it only checks registry/loadability by capability and executes the
                        # declared module entrypoint; it does not know the module domain.
                        if module_blueprint.get("status") == "module_already_registered":
                            executed_module = await self._execute_registered_module(
                                run_id=run_id,
                                node_id=node_id,
                                step_id=step_id,
                                capability=required_capability or "unknown_capability",
                                step=step,
                                state=state,
                                component_type="runtime_registered_module",
                            )
                            if executed_module:
                                module_result = executed_module.get("result", {})
                                execution_steps.append({
                                    "step_id": step_id,
                                    "status": "executed" if self._is_success_result(module_result) else "module_execution_failed",
                                    "module": executed_module.get("registry_record"),
                                    "input": executed_module.get("input"),
                                    "result": module_result,
                                    "provenance": module_result.get("provenance") if isinstance(module_result, dict) else None,
                                    "source_step": step,
                                })
                                if not self._is_success_result(module_result):
                                    blocked_steps.append({
                                        "step_id": step_id,
                                        "status": "module_execution_failed",
                                        "capability": required_capability,
                                        "reason": self._result_error_message(module_result, "Module execution failed."),
                                        "source_step": step,
                                        "module_result": module_result,
                                    })
                                continue

                            blocked_steps.append({
                                "step_id": step_id,
                                "status": "registered_module_not_executable",
                                "capability": required_capability,
                                "reason": "A module is registered for this capability but could not be loaded or executed.",
                                "source_step": step,
                                "generated_module": module_blueprint,
                            })
                            continue

                        missing_tools.append({"step_id": step_id, "capability": required_capability, "generated_tool_spec": generated_spec, "generated_module": module_blueprint})
                        await event_bus.emit(run_id, {
                            "type": "TOOL_AND_MODULE_REQUEST_GENERATED",
                            "title": "Tool/module request generated",
                            "message": f"Generated request for capability={required_capability or 'unknown_capability'}",
                            "node_id": node_id,
                            "step_id": step_id,
                            "result": {"tool": generated_spec, "module": module_blueprint},
                        })
                        blocked_steps.append({"step_id": step_id, "status": "missing_tool_implementation", "capability": required_capability, "source_step": step})
                        continue

            if self._requires_confirmation(step, tool, state):
                safety_holds.append({
                    "step_id": step_id,
                    "status": "waiting_for_human_confirmation",
                    "reason": "Step or runtime tool policy requires explicit human confirmation.",
                    "source_step": step,
                    "tool": self._public_tool_spec(tool),
                })
                blocked_steps.append({
                    "step_id": step_id,
                    "status": "waiting_for_human_confirmation",
                    "reason": "Human confirmation required by runtime policy.",
                    "source_step": step,
                })
                continue

            tool_input = self._build_tool_input(
                step=step,
                run_id=run_id,
                node_id=node_id,
                step_id=step_id,
                user_input=state.get("input", ""),
            )
            tool_result = self.tool_runner.run_tool(
                tool,
                tool_input,
                run_id=run_id,
                node_id=node_id,
                step_id=step_id,
                capability=required_capability,
            )

            if tool_result.get("status") != "success":
                repaired_tool = await self._try_repair_executable_tool(
                    run_id=run_id,
                    node_id=node_id,
                    step_id=step_id,
                    capability=required_capability or "unknown_capability",
                    step=step,
                    state=state,
                    failed_tool=tool,
                    failed_result=tool_result,
                )
                if repaired_tool:
                    tool = repaired_tool
                    tool_result = self.tool_runner.run_tool(
                tool,
                tool_input,
                run_id=run_id,
                node_id=node_id,
                step_id=step_id,
                capability=required_capability,
            )

            if isinstance(tool_result, dict) and tool_result.get("provenance"):
                await event_bus.emit(run_id, {
                    "type": "EXECUTION_PROVENANCE_RECORDED",
                    "title": "Execution provenance recorded",
                    "message": f"Recorded provenance for step={step_id}",
                    "node_id": node_id,
                    "step_id": step_id,
                    "result": tool_result.get("provenance"),
                })

            execution_steps.append({
                "step_id": step_id,
                "status": "executed" if tool_result.get("status") == "success" else "tool_execution_failed",
                "tool": self._public_tool_spec(tool),
                "input": tool_input,
                "result": tool_result,
                "provenance": tool_result.get("provenance") if isinstance(tool_result, dict) else None,
                "source_step": step,
            })

            if tool_result.get("status") != "success":
                blocked_steps.append({
                    "step_id": step_id,
                    "status": "tool_execution_failed",
                    "reason": tool_result.get("error", {}).get("message") or "Tool execution failed.",
                    "source_step": step,
                    "tool_result": tool_result,
                })

        status = self._overall_status(execution_steps, blocked_steps, human_interactions, missing_tools, safety_holds)
        result = {
            "_executor_type": "tool_call",
            "_node_id": node_id,
            "status": status,
            "execution_steps": execution_steps,
            "blocked_steps": blocked_steps,
            "human_interactions": human_interactions,
            "missing_tools": missing_tools,
            "generated_modules": generated_modules,
            "safety_holds": safety_holds,
            "normalized_workflow": normalized_plan,
            "summary": {
                "planned": len(planned_steps),
                "executed": len([step for step in execution_steps if step.get("status") == "executed"]),
                "failed": len([step for step in execution_steps if step.get("status") in {"tool_execution_failed", "module_execution_failed"}]),
                "blocked": len(blocked_steps),
                "human_interactions": len(human_interactions),
                "missing_tools": len(missing_tools),
                "generated_modules": len(generated_modules),
                "safety_holds": len(safety_holds),
            },
        }

        await event_bus.emit(run_id, {
            "type": "EXECUTION_PLANNER_RESULT",
            "title": "Execution planner result",
            "message": f"status={status}, executed={len([step for step in execution_steps if step.get('status') == 'executed'])}, blocked={len(blocked_steps)}",
            "node_id": node_id,
            "result": result,
        })
        return result

    async def _execute_registered_module(
        self,
        *,
        run_id: str,
        node_id: str,
        step_id: str,
        capability: str,
        step: dict[str, Any],
        state: dict[str, Any],
        component_type: str = "runtime_module",
    ) -> dict[str, Any] | None:
        """Load and execute an already-registered runtime module by capability.

        This is the v50 continuation bridge. When a previous run or an earlier
        phase generated/registered a module, execution must not stop at a
        generated-capability review. It should reuse the registered module and
        continue the workflow. The method is domain-neutral: it only uses
        capability metadata and the module registry.
        """
        module = self.module_loader.load_by_capability(capability)
        if module is None:
            await event_bus.emit(run_id, {
                "type": "MODULE_REUSE_UNAVAILABLE",
                "title": "Registered module unavailable",
                "message": f"A module is registered for capability={capability}, but it could not be loaded.",
                "node_id": node_id,
                "step_id": step_id,
            })
            return None

        module_record = self.module_loader.registry.find_by_capability(capability) or {"module_id": capability}
        module_input = self._build_tool_input(
            step=step,
            run_id=run_id,
            node_id=node_id,
            step_id=step_id,
            user_input=state.get("input", ""),
        )
        await event_bus.emit(run_id, {
            "type": "MODULE_REUSE_EXECUTION_STARTED",
            "title": "Reusable module execution started",
            "message": f"Executing registered runtime module for capability={capability}",
            "node_id": node_id,
            "step_id": step_id,
            "result": {"module": module_record, "input": module_input},
        })
        trace = self.provenance.start(
            run_id=run_id,
            node_id=node_id,
            step_id=step_id,
            component_type=component_type,
            component_id=str(module_record.get("module_id") or capability),
            capability=capability,
            input_data=module_input,
            artifact=module_record,
        )
        try:
            raw_result = module.run(module_input)
            result = self._normalize_runtime_execution_result(raw_result, source=component_type)
            trace = self.provenance.finish(
                trace,
                output=result,
                status="success" if self._is_success_result(result) else "error",
                error=result.get("error") if isinstance(result, dict) else None,
            )
            result = self.provenance.attach(result, trace)
        except Exception as exc:
            result = {"status": "error", "error": {"message": str(exc)}, "data": {}, "source": component_type}
            trace = self.provenance.finish(trace, output=result, status="error", error=result.get("error"))
            result = self.provenance.attach(result, trace)

        await event_bus.emit(run_id, {
            "type": "MODULE_REUSE_EXECUTED",
            "title": "Reusable module executed",
            "message": f"Registered module executed for capability={capability}",
            "node_id": node_id,
            "step_id": step_id,
            "result": result,
        })
        if isinstance(result, dict) and result.get("provenance"):
            await event_bus.emit(run_id, {
                "type": "EXECUTION_PROVENANCE_RECORDED",
                "title": "Execution provenance recorded",
                "message": f"Recorded provenance for step={step_id}",
                "node_id": node_id,
                "step_id": step_id,
                "result": result.get("provenance"),
            })
        return {"module": module, "registry_record": module_record, "input": module_input, "result": result}



    def _normalize_runtime_execution_result(self, value: Any, *, source: str) -> dict[str, Any]:
        """Normalize runtime tool/module outputs into a generic success/error contract.

        Runtime-generated modules are allowed to return a plain data object, for
        example {"temperature": 25, "condition": "Sunny"}. A missing `status`
        field must not be treated as failure. This method stays domain-neutral:
        it only checks generic error/status shape and wraps useful payloads into
        the common result contract.
        """
        if isinstance(value, dict):
            raw_status = str(value.get("status", "")).lower().strip()
            has_error = bool(value.get("error"))

            if raw_status in {"success", "ok", "executed"} and not has_error:
                normalized = dict(value)
                normalized["status"] = "success"
                normalized.setdefault("source", source)
                if "data" not in normalized:
                    data = {k: v for k, v in value.items() if k not in {"status", "source", "requires_human_confirmation"}}
                    normalized["data"] = data
                return normalized

            if raw_status in {"error", "failed", "failure"} or has_error:
                error = value.get("error") if isinstance(value.get("error"), dict) else {"message": str(value.get("error") or value)}
                return {
                    "status": "error",
                    "error": error,
                    "data": value.get("data") if isinstance(value.get("data"), dict) else {},
                    "source": value.get("source") or source,
                    "requires_human_confirmation": bool(value.get("requires_human_confirmation", False)),
                }

            # Plain dict payload without a status is a valid successful result.
            return {
                "status": "success",
                "data": value,
                "source": source,
                "requires_human_confirmation": bool(value.get("requires_human_confirmation", False)),
            }

        if value is None:
            return {
                "status": "error",
                "error": {"message": "Runtime component returned no result."},
                "data": {},
                "source": source,
                "requires_human_confirmation": False,
            }

        return {
            "status": "success",
            "data": {"value": value},
            "source": source,
            "requires_human_confirmation": False,
        }

    def _is_success_result(self, result: Any) -> bool:
        return isinstance(result, dict) and result.get("status") == "success"

    def _result_error_message(self, result: Any, fallback: str) -> str:
        if isinstance(result, dict):
            error = result.get("error")
            if isinstance(error, dict):
                message = error.get("message")
                if isinstance(message, str) and message.strip():
                    return message.strip()
            if isinstance(result.get("message"), str) and result.get("message").strip():
                return result.get("message").strip()
        return fallback



    def _build_tool_input(
        self,
        *,
        step: dict[str, Any],
        run_id: str,
        node_id: str,
        step_id: str,
        user_input: str,
    ) -> dict[str, Any]:
        """Build a generic, schema-friendly tool input object.

        Runtime-generated tools may declare schemas that require fields at the
        top level, while workflow planning usually stores values under
        parameters.known / parameters.optional. To keep ai_core domain-neutral,
        this method does not infer meanings from field names. It simply exposes
        the already-structured runtime metadata in both canonical nested form
        and flattened top-level form so reusable generated tools can validate
        reliably.
        """
        params = step.get("parameters") if isinstance(step.get("parameters"), dict) else {}
        known = params.get("known") if isinstance(params.get("known"), dict) else {}
        optional = params.get("optional") if isinstance(params.get("optional"), dict) else {}

        tool_input: dict[str, Any] = {}
        for source in (known, optional):
            for key, value in source.items():
                if key not in tool_input:
                    tool_input[str(key)] = value

        tool_input.update({
            "parameters": params,
            "known": known,
            "optional": optional,
            "context": {
                "run_id": run_id,
                "node_id": node_id,
                "step_id": step_id,
                "user_input": user_input,
            },
            "source_step": step,
        })
        return tool_input

    async def _try_generate_executable_module(
        self,
        *,
        run_id: str,
        node_id: str,
        step_id: str,
        capability: str,
        step: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any] | None:
        api_discovery = await self.api_discovery.discover(
            run_id=run_id,
            node_id=node_id,
            capability=capability,
            step=step,
            user_input=state.get("input", ""),
        )
        generation_request = {
            "request_type": "runtime_module_artifact_generation",
            "capability": capability,
            "step": step,
            "user_input": state.get("input", ""),
            "api_discovery": api_discovery,
            "constraints": {
                "must_be_reusable": True,
                "must_define_runtime_interface": ["validate_config", "health_check", "run"],
                "must_return_schema_compatible_output": True,
                "must_not_log_secrets": True,
                "must_not_perform_irreversible_actions_without_confirmation": True,
                "no_mock_data": True,
                "must_use_real_network_when_external_data_is_required": True,
                "must_include_request_response_evidence": True,
                "must_declare_execution_claims": True,
                "must_include_live_verification_metadata": True,
            },
            "expected_contract": {
                "module_id": "string",
                "manifest": "module.json compatible object with execution_claims, api_discovery, verification",
                "files": {"module.py": "python source code"},
            },
        }
        await event_bus.emit(run_id, {
            "type": "MODULE_GENERATION_STARTED",
            "title": "Runtime module generation started",
            "message": f"Generating reusable module artifact for capability={capability}",
            "node_id": node_id,
            "step_id": step_id,
            "result": generation_request,
        })
        try:
            artifact = await self.module_artifact_generator.generate_artifact(
                run_id=run_id, node_id=node_id, generation_request=generation_request
            )
            installed = self.module_installer.install_artifact(
                artifact=artifact, capability=capability, source_step=step, user_input=state.get("input", "")
            )
            await event_bus.emit(run_id, {
                "type": "MODULE_REGISTERED",
                "title": "Runtime module registered",
                "message": f"Reusable runtime module registered for capability={capability}",
                "node_id": node_id,
                "step_id": step_id,
                "result": installed,
            })
            module = self.module_loader.load_by_capability(capability)
            if module is None:
                raise RuntimeError("Generated module was registered but could not be loaded.")
            module_input = self._build_tool_input(
                step=step, run_id=run_id, node_id=node_id, step_id=step_id, user_input=state.get("input", "")
            )
            await event_bus.emit(run_id, {
                "type": "MODULE_EXECUTION_STARTED",
                "title": "Runtime module execution started",
                "message": f"Executing generated module for capability={capability}",
                "node_id": node_id,
                "step_id": step_id,
            })
            trace = self.provenance.start(
                run_id=run_id,
                node_id=node_id,
                step_id=step_id,
                component_type="runtime_generated_module",
                component_id=str(installed.get("module_id") or capability),
                capability=capability,
                input_data=module_input,
                artifact=installed,
            )
            raw_result = module.run(module_input)
            result = self._normalize_runtime_execution_result(raw_result, source="runtime_generated_module")
            trace = self.provenance.finish(
                trace,
                output=result,
                status="success" if self._is_success_result(result) else "error",
                error=result.get("error") if isinstance(result, dict) else None,
            )
            result = self.provenance.attach(result, trace)
            await event_bus.emit(run_id, {
                "type": "MODULE_EXECUTED",
                "title": "Runtime module executed",
                "message": f"Generated module executed for capability={capability}",
                "node_id": node_id,
                "step_id": step_id,
                "result": result,
            })
            if isinstance(result, dict) and result.get("provenance"):
                await event_bus.emit(run_id, {
                    "type": "EXECUTION_PROVENANCE_RECORDED",
                    "title": "Execution provenance recorded",
                    "message": f"Recorded provenance for step={step_id}",
                    "node_id": node_id,
                    "step_id": step_id,
                    "result": result.get("provenance"),
                })
            return {"module": module, "registry_record": installed, "result": result}
        except Exception as exc:
            await event_bus.emit(run_id, {
                "type": "MODULE_GENERATION_FAILED",
                "title": "Runtime module generation failed",
                "message": str(exc),
                "node_id": node_id,
                "step_id": step_id,
            })
            return None


    async def _try_generate_executable_tool(
        self,
        *,
        run_id: str,
        node_id: str,
        step_id: str,
        capability: str,
        step: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Ask the runtime intelligence layer to generate a reusable tool artifact.

        This is generic: ai_core does not choose an API, endpoint, provider, or
        business strategy. The LLM/runtime-generated artifact must declare its
        files, manifest, schemas, safety, retry/timeout behavior, and callable.
        """
        api_discovery = await self.api_discovery.discover(
            run_id=run_id,
            node_id=node_id,
            capability=capability,
            step=step,
            user_input=state.get("input", ""),
        )
        generation_request = {
            "request_type": "runtime_tool_artifact_generation",
            "capability": capability,
            "step": step,
            "user_input": state.get("input", ""),
            "api_discovery": api_discovery,
            "constraints": {
                "must_be_reusable": True,
                "must_return_schema_compatible_output": True,
                "must_not_log_secrets": True,
                "must_not_perform_irreversible_actions_without_confirmation": True,
                "must_define_retry_and_timeout_when_using_network": True,
                "must_use_real_network_when_external_data_is_required": True,
                "must_include_request_response_evidence": True,
                "must_declare_execution_claims": True,
                "must_include_live_verification_metadata": True,
                "no_mock_data": True,
            },
            "expected_contract": {
                "tool_id": "string",
                "manifest": "tool.json compatible object with execution_claims, api_discovery, verification",
                "files": {"tool.py": "python source code"},
            },
        }
        await event_bus.emit(run_id, {
            "type": "RUNTIME_TOOL_GENERATION_STARTED",
            "title": "Runtime tool generation started",
            "message": f"Generating reusable tool artifact for capability={capability}",
            "node_id": node_id,
            "step_id": step_id,
            "result": generation_request,
        })
        try:
            artifact = await self.artifact_generator.generate_artifact(
                run_id=run_id,
                node_id=node_id,
                generation_request=generation_request,
            )
            if not isinstance(artifact, dict) or not artifact.get("files"):
                await event_bus.emit(run_id, {
                    "type": "RUNTIME_TOOL_GENERATION_FAILED",
                    "title": "Runtime tool generation failed",
                    "message": "Generated artifact was empty or invalid.",
                    "node_id": node_id,
                    "step_id": step_id,
                    "result": artifact,
                })
                return None
            installed = self.artifact_installer.install_artifact(
                artifact=artifact,
                capability=capability,
                source_step=step,
                user_input=state.get("input", ""),
            )
            await event_bus.emit(run_id, {
                "type": "RUNTIME_TOOL_GENERATED_AND_REGISTERED",
                "title": "Runtime tool generated and registered",
                "message": f"Reusable runtime tool registered for capability={capability}",
                "node_id": node_id,
                "step_id": step_id,
                "result": self._public_tool_spec(installed),
            })
            return installed
        except Exception as exc:
            await event_bus.emit(run_id, {
                "type": "RUNTIME_TOOL_GENERATION_FAILED",
                "title": "Runtime tool generation failed",
                "message": str(exc),
                "node_id": node_id,
                "step_id": step_id,
            })
            return None


    async def _try_repair_executable_tool(
        self,
        *,
        run_id: str,
        node_id: str,
        step_id: str,
        capability: str,
        step: dict[str, Any],
        state: dict[str, Any],
        failed_tool: dict[str, Any],
        failed_result: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Repair a generated runtime tool once when execution fails.

        This remains generic. ai_core does not know why the capability exists or
        which API should be used. It only sends the runtime failure, tool spec,
        and source step back to the runtime code-generation route and installs a
        complete replacement artifact.
        """
        error = failed_result.get("error") if isinstance(failed_result.get("error"), dict) else failed_result
        generation_request = {
            "request_type": "runtime_tool_artifact_repair",
            "capability": capability,
            "step": step,
            "user_input": state.get("input", ""),
            "failed_tool": self._public_tool_spec(failed_tool),
            "failed_result": failed_result,
            "constraints": {
                "must_be_reusable": True,
                "must_return_schema_compatible_output": True,
                "must_not_log_secrets": True,
                "must_not_perform_irreversible_actions_without_confirmation": True,
                "must_define_retry_and_timeout_when_using_network": True,
                "no_mock_data": True,
                "must_define_all_called_functions": True,
            },
            "expected_contract": {
                "tool_id": "string",
                "manifest": "tool.json compatible object",
                "files": {"tool.py": "python source code"},
            },
        }
        await event_bus.emit(run_id, {
            "type": "RUNTIME_TOOL_REPAIR_STARTED",
            "title": "Runtime tool repair started",
            "message": f"Repairing generated tool for capability={capability}: {error}",
            "node_id": node_id,
            "step_id": step_id,
            "result": generation_request,
        })
        try:
            artifact = await self.artifact_generator.repair_artifact(
                run_id=run_id,
                node_id=node_id,
                generation_request=generation_request,
                failed_artifact={"tool": failed_tool},
                error=error,
            )
            installed = self.artifact_installer.install_artifact(
                artifact=artifact,
                capability=capability,
                source_step=step,
                user_input=state.get("input", ""),
            )
            await event_bus.emit(run_id, {
                "type": "RUNTIME_TOOL_REPAIRED_AND_REGISTERED",
                "title": "Runtime tool repaired and registered",
                "message": f"Repaired reusable runtime tool for capability={capability}",
                "node_id": node_id,
                "step_id": step_id,
                "result": self._public_tool_spec(installed),
            })
            return installed
        except Exception as exc:
            await event_bus.emit(run_id, {
                "type": "RUNTIME_TOOL_REPAIR_FAILED",
                "title": "Runtime tool repair failed",
                "message": str(exc),
                "node_id": node_id,
                "step_id": step_id,
            })
            return None

    def _requires_confirmation(self, step: dict[str, Any], tool: dict[str, Any], state: dict[str, Any]) -> bool:
        confirmations = state.get("human_confirmations") if isinstance(state, dict) else []
        step_id = str(step.get("step_id") or step.get("task_id") or "")
        if isinstance(confirmations, list):
            for item in confirmations:
                if isinstance(item, dict):
                    holds = item.get("safety_holds") if isinstance(item.get("safety_holds"), list) else []
                    if any(str(h.get("step_id", "")) == step_id for h in holds if isinstance(h, dict)):
                        return False

        tool_safety = tool.get("safety") if isinstance(tool.get("safety"), dict) else {}
        step_safety = step.get("safety") if isinstance(step.get("safety"), dict) else {}
        runtime_safety = {**step_safety, **tool_safety}

        # Runtime/tool safety declaration is authoritative. This avoids treating
        # a model's generic requires_human_confirmation=true as business logic.
        if runtime_safety.get("requires_human_confirmation") is False:
            return False
        if runtime_safety.get("can_perform_irreversible_action") is True:
            return True
        if runtime_safety.get("can_write_external_data") is True:
            return True
        if runtime_safety.get("requires_human_confirmation") is True:
            return True
        return bool(step.get("requires_human_confirmation", False) and runtime_safety)


    def _has_executable_implementation(self, tool: dict[str, Any]) -> bool:
        implementation = tool.get("implementation")
        return isinstance(implementation, dict) and bool(
            implementation.get("module_path") or implementation.get("path")
        )

    def _public_tool_spec(self, tool: dict[str, Any]) -> dict[str, Any]:
        public = dict(tool)
        implementation = public.get("implementation")
        if isinstance(implementation, dict):
            public["implementation"] = {
                "type": implementation.get("type"),
                "function": implementation.get("function") or implementation.get("callable") or "run",
                "module_path": implementation.get("module_path") or implementation.get("path"),
            }
        return public

    def _capability_name(self, value: Any) -> str | None:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            for key in ["capability", "capability_id", "name", "id"]:
                candidate = value.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()
        return None

    def _normalize_human_interaction(self, value: Any) -> dict[str, Any]:
        if isinstance(value, bool):
            return {"required": value}
        if isinstance(value, dict):
            return {"required": bool(value.get("required", True)), **value}
        return {"required": False}

    def _missing_fields(self, step: dict[str, Any]) -> list[str]:
        explicit = step.get("missing_fields")
        if isinstance(explicit, list) and explicit:
            return list(dict.fromkeys(str(x) for x in explicit if str(x).strip()))

        params = step.get("parameters", {})
        missing: list[str] = []
        if isinstance(params, dict):
            raw = params.get("missing_required")
            if isinstance(raw, list):
                missing.extend([str(x) for x in raw if str(x).strip()])
            elif isinstance(raw, dict):
                for key, value in raw.items():
                    if value in [None, "", [], {}]:
                        missing.append(str(key))
        return list(dict.fromkeys(missing))

    def _overall_status(self, execution_steps, blocked_steps, human_interactions, missing_tools, safety_holds) -> str:
        if human_interactions:
            return "waiting_for_human_information"
        if missing_tools:
            return "missing_tool_implementation"
        if safety_holds:
            return "waiting_for_human_confirmation"
        if blocked_steps and not execution_steps:
            return "blocked"
        if blocked_steps and any(step.get("status") in {"tool_execution_failed", "module_execution_failed"} for step in execution_steps):
            return "tool_execution_failed"
        if execution_steps and blocked_steps:
            return "partially_executed"
        if execution_steps and all(step.get("status") == "executed" for step in execution_steps):
            return "executed"
        if execution_steps:
            return "ready"
        return "no_executable_steps"
