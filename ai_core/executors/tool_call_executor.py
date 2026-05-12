from __future__ import annotations

from typing import Any

from ai_core.events.event_bus import event_bus
from ai_core.tools.runtime_tool_registry import RuntimeToolRegistry
from ai_core.modules.module_builder import RuntimeModuleBuilder


class ToolCallExecutor:
    """
    Generic tool-call executor.

    It does not know any business/domain-specific concepts.

    It reads workflow_planning.planned_steps and produces an execution state:
    - executable steps
    - blocked steps
    - human interaction requests
    - missing tool specs
    - safety holds
    """

    def __init__(self) -> None:
        self.tool_registry = RuntimeToolRegistry()
        self.module_builder = RuntimeModuleBuilder()

    async def execute(
        self,
        workflow_node: dict[str, Any],
        node_config: dict[str, Any],
        state: dict[str, Any],
        capability_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Standard executor interface used by NodeRunner."""
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
        planned_steps = workflow_plan.get("planned_steps", [])

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
            }

        execution_steps = []
        blocked_steps = []
        human_interactions = []
        missing_tools = []
        safety_holds = []

        for index, step in enumerate(planned_steps):
            step_id = step.get("step_id") or step.get("task_id") or f"step_{index + 1}"
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

            if human_interaction.get("required"):
                interaction = {
                    "step_id": step_id,
                    "type": human_interaction.get("type") or step.get("step_type") or "human_interaction",
                    "objective": step.get("objective"),
                    "fields": human_interaction.get("fields") or self._missing_fields(step),
                    "reason": "Step requires human interaction before execution.",
                    "source_step": step,
                }
                human_interactions.append(interaction)
                blocked_steps.append({
                    "step_id": step_id,
                    "status": "waiting_for_human_interaction",
                    "reason": "Human interaction required.",
                    "source_step": step,
                })
                continue

            if requires_confirmation:
                safety_holds.append({
                    "step_id": step_id,
                    "status": "waiting_for_human_confirmation",
                    "reason": "Step requires explicit human confirmation.",
                    "source_step": step,
                })
                blocked_steps.append({
                    "step_id": step_id,
                    "status": "waiting_for_human_confirmation",
                    "reason": "Human confirmation required.",
                    "source_step": step,
                })
                continue

            missing_fields = self._missing_fields(step)
            if missing_fields:
                human_interactions.append({
                    "step_id": step_id,
                    "type": "collect_missing_information",
                    "objective": f"Collect missing information for {step_id}.",
                    "fields": missing_fields,
                    "reason": "Required parameters are missing.",
                    "source_step": step,
                })
                blocked_steps.append({
                    "step_id": step_id,
                    "status": "missing_required_information",
                    "missing_fields": missing_fields,
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
                missing_tools.append({
                    "step_id": step_id,
                    "capability": required_capability,
                    "generated_tool_spec": generated_spec,
                })
                await event_bus.emit(run_id, {
                    "type": "TOOL_BLUEPRINT_GENERATED",
                    "title": "Tool blueprint generated",
                    "message": f"Generated blueprint/codegen request for capability={required_capability}",
                    "node_id": node_id,
                    "step_id": step_id,
                    "result": generated_spec,
                })

                module_result = self.module_builder.ensure_module_for_capability(
                    capability=required_capability or "unknown_capability",
                    source_step=step,
                    user_input=state.get("input", ""),
                )
                await event_bus.emit(run_id, {
                    "type": "MODULE_BLUEPRINT_GENERATED",
                    "title": "Module blueprint generated",
                    "message": f"Generated module blueprint for capability={required_capability}",
                    "node_id": node_id,
                    "step_id": step_id,
                    "result": module_result,
                })
                blocked_steps.append({
                    "step_id": step_id,
                    "status": "missing_tool_implementation",
                    "capability": required_capability,
                    "source_step": step,
                })
                continue

            execution_steps.append({
                "step_id": step_id,
                "status": "ready_to_execute",
                "tool": tool,
                "input": step.get("parameters", {}),
                "source_step": step,
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
            "safety_holds": safety_holds,
            "summary": {
                "planned": len(planned_steps),
                "ready_to_execute": len(execution_steps),
                "blocked": len(blocked_steps),
                "human_interactions": len(human_interactions),
                "missing_tools": len(missing_tools),
                "safety_holds": len(safety_holds),
            },
        }

        await event_bus.emit(run_id, {
            "type": "EXECUTION_PLANNER_RESULT",
            "title": "Execution planner result",
            "message": f"status={status}, ready={len(execution_steps)}, blocked={len(blocked_steps)}",
            "node_id": node_id,
            "result": result,
        })

        return result

    def _capability_name(self, value: Any) -> str | None:
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return value.get("capability") or value.get("name") or value.get("id")
        return None

    def _normalize_human_interaction(self, value: Any) -> dict[str, Any]:
        if isinstance(value, bool):
            return {"required": value}
        if isinstance(value, dict):
            return {"required": bool(value.get("required", True)), **value}
        return {"required": False}

    def _missing_fields(self, step: dict[str, Any]) -> list[str]:
        params = step.get("parameters", {})
        missing = []

        if isinstance(params, dict):
            raw = params.get("missing_required")

            if isinstance(raw, list):
                missing.extend([str(x) for x in raw])

            elif isinstance(raw, dict):
                for key, value in raw.items():
                    if value in [None, "", [], {}]:
                        missing.append(str(key))

        return list(dict.fromkeys(missing))

    def _overall_status(self, execution_steps, blocked_steps, human_interactions, missing_tools, safety_holds) -> str:
        if human_interactions:
            return "waiting_for_human_information"
        if safety_holds:
            return "waiting_for_human_confirmation"
        if missing_tools:
            return "missing_tool_implementation"
        if blocked_steps and not execution_steps:
            return "blocked"
        if execution_steps and blocked_steps:
            return "partially_ready"
        if execution_steps:
            return "ready"
        return "no_executable_steps"
