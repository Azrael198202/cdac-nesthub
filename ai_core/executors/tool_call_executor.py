from __future__ import annotations

from typing import Any

from ai_core.events.event_bus import event_bus
from ai_core.tools.runtime_tool_registry import RuntimeToolRegistry
from ai_core.modules.module_builder import RuntimeModuleBuilder
from ai_core.workflow.workflow_normalizer import WorkflowNormalizer
from ai_core.tools.generic_tool_runner import GenericToolRunner
from ai_core.tools.runtime_tool_artifact_generator import RuntimeToolArtifactGenerator
from ai_core.tools.runtime_generated_tool_installer import RuntimeGeneratedToolInstaller


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
        self.normalizer = WorkflowNormalizer()
        self.tool_runner = GenericToolRunner()
        self.artifact_generator = RuntimeToolArtifactGenerator()
        self.artifact_installer = RuntimeGeneratedToolInstaller()

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
                        module_result = self.module_builder.ensure_module_for_capability(
                            capability=required_capability or "unknown_capability",
                            source_step=step,
                            user_input=state.get("input", ""),
                        )
                        generated_modules.append({
                            "step_id": step_id,
                            "capability": required_capability,
                            "generated_module": module_result,
                        })
                        missing_tools.append({
                            "step_id": step_id,
                            "capability": required_capability,
                            "generated_tool_spec": generated_spec,
                            "generated_module": module_result,
                        })
                        await event_bus.emit(run_id, {
                            "type": "TOOL_AND_MODULE_REQUEST_GENERATED",
                            "title": "Tool/module request generated",
                            "message": f"Generated request for capability={required_capability or 'unknown_capability'}",
                            "node_id": node_id,
                            "step_id": step_id,
                            "result": {
                                "tool": generated_spec,
                                "module": module_result,
                            },
                        })
                        blocked_steps.append({
                            "step_id": step_id,
                            "status": "missing_tool_implementation",
                            "capability": required_capability,
                            "source_step": step,
                        })
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

            tool_input = {
                "parameters": step.get("parameters", {}),
                "context": {
                    "run_id": run_id,
                    "node_id": node_id,
                    "step_id": step_id,
                    "user_input": state.get("input", ""),
                },
                "source_step": step,
            }
            tool_result = self.tool_runner.run_tool(tool, tool_input)
            execution_steps.append({
                "step_id": step_id,
                "status": "executed" if tool_result.get("status") == "success" else "tool_execution_failed",
                "tool": self._public_tool_spec(tool),
                "input": step.get("parameters", {}),
                "result": tool_result,
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
                "failed": len([step for step in execution_steps if step.get("status") == "tool_execution_failed"]),
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
        generation_request = {
            "request_type": "runtime_tool_artifact_generation",
            "capability": capability,
            "step": step,
            "user_input": state.get("input", ""),
            "constraints": {
                "must_be_reusable": True,
                "must_return_schema_compatible_output": True,
                "must_not_log_secrets": True,
                "must_not_perform_irreversible_actions_without_confirmation": True,
                "must_define_retry_and_timeout_when_using_network": True,
                "no_mock_data": True,
            },
            "expected_contract": {
                "tool_id": "string",
                "manifest": "tool.json compatible object",
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
        if blocked_steps and any(step.get("status") == "tool_execution_failed" for step in execution_steps):
            return "tool_execution_failed"
        if execution_steps and blocked_steps:
            return "partially_executed"
        if execution_steps and all(step.get("status") == "executed" for step in execution_steps):
            return "executed"
        if execution_steps:
            return "ready"
        return "no_executable_steps"
