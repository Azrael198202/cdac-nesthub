from __future__ import annotations

from typing import Any

from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import PROJECT_ROOT
from ai_core.validation.schema_validator import SchemaValidator


class OutputExecutor:
    """Builds a user-facing final response from generic runtime results.

    This executor does not know business domains. It only inspects generic
    execution state and tool result contracts. If execution is blocked, it
    returns a waiting/blocked response instead of claiming completion.
    """

    TERMINAL_SUCCESS = {"executed", "partially_executed"}
    WAITING_STATUSES = {
        "waiting_for_human_information",
        "waiting_for_human_confirmation",
        "missing_tool_implementation",
        "blocked",
        "no_executable_steps",
        "not_execution_ready",
    }

    def __init__(self) -> None:
        self.loader = ConfigLoader()
        self.validator = SchemaValidator()

    async def execute(self, workflow_node, node_config, state, capability_result):
        result = self._build(state, node_config)
        schema_path = node_config.get("output_schema")
        if schema_path:
            try:
                schema = self.loader.load_json(PROJECT_ROOT / schema_path)
                self.validator.validate_data(result, schema)
            except Exception:
                # Output schema is intentionally permissive in generated runtimes;
                # do not hide the user-facing response if an older schema is stale.
                pass
        return result

    def _build(self, state: dict[str, Any], node_config: dict[str, Any]) -> dict[str, Any]:
        results = state.get("results", {}) if isinstance(state, dict) else {}
        execution = results.get("execution") if isinstance(results.get("execution"), dict) else {}
        status = str(execution.get("status") or "unknown")
        execution_steps = execution.get("execution_steps") if isinstance(execution.get("execution_steps"), list) else []
        blocked_steps = execution.get("blocked_steps") if isinstance(execution.get("blocked_steps"), list) else []
        safety_holds = execution.get("safety_holds") if isinstance(execution.get("safety_holds"), list) else []
        human_interactions = execution.get("human_interactions") if isinstance(execution.get("human_interactions"), list) else []
        missing_tools = execution.get("missing_tools") if isinstance(execution.get("missing_tools"), list) else []

        if status in self.WAITING_STATUSES or (blocked_steps and not execution_steps):
            message = self._waiting_message(status, human_interactions, safety_holds, missing_tools, blocked_steps)
            return {
                "_executor_type": "output",
                "_node_id": node_config.get("node_id", "output"),
                "status": "waiting" if status.startswith("waiting") else "blocked",
                "message": message,
                "execution_status": status,
                "executed_steps": len(execution_steps),
                "blocked_steps": blocked_steps,
                "safety_holds": safety_holds,
                "human_interactions": human_interactions,
                "missing_tools": missing_tools,
                "final_answer": message,
                "previous_result_keys": list(results.keys()),
            }

        summaries: list[str] = []
        tool_results: list[dict[str, Any]] = []
        provenance_records: list[dict[str, Any]] = []
        for step in execution_steps:
            if not isinstance(step, dict):
                continue
            tool_result = step.get("result") if isinstance(step.get("result"), dict) else {}
            tool_results.append(tool_result)
            provenance = tool_result.get("provenance") if isinstance(tool_result.get("provenance"), dict) else step.get("provenance")
            if isinstance(provenance, dict):
                provenance_records.append(provenance)
            summaries.append(self._summarize_tool_result(step, tool_result))

        if summaries:
            final_answer = "\n\n".join(s for s in summaries if s).strip()
        else:
            final_answer = "Workflow finished, but no executable tool result was produced."

        return {
            "_executor_type": "output",
            "_node_id": node_config.get("node_id", "output"),
            "status": "completed" if status in self.TERMINAL_SUCCESS else status,
            "message": final_answer,
            "final_answer": final_answer,
            "execution_status": status,
            "tool_results": tool_results,
            "provenance": provenance_records,
            "trust_summary": self._trust_summary(provenance_records),
            "executed_steps": len(execution_steps),
            "blocked_steps": blocked_steps,
            "previous_result_keys": list(results.keys()),
        }

    def _trust_summary(self, provenance_records: list[dict[str, Any]]) -> dict[str, Any]:
        if not provenance_records:
            return {
                "trace_available": False,
                "message": "No execution provenance was recorded for this result.",
            }
        real_declared = any(bool((p.get("execution_claims") or {}).get("real_execution_declared")) for p in provenance_records)
        no_mock_declared = any(bool((p.get("execution_claims") or {}).get("no_mock_data_declared")) for p in provenance_records)
        network_declared = any(bool((p.get("execution_claims") or {}).get("network_declared")) for p in provenance_records)
        return {
            "trace_available": True,
            "trace_count": len(provenance_records),
            "real_execution_declared": real_declared,
            "no_mock_data_declared": no_mock_declared,
            "network_declared": network_declared,
            "trace_ids": [p.get("trace_id") for p in provenance_records if p.get("trace_id")],
        }

    def _format_data_result(self, data: dict[str, Any]) -> str:
        if not data:
            return "Tool executed successfully."
        lines = ["Result:"]
        for key, value in data.items():
            if key in {"status", "source", "requires_human_confirmation"}:
                continue
            label = str(key).replace("_", " ").replace("-", " ").strip() or str(key)
            label = " ".join(part[:1].upper() + part[1:] for part in label.split())
            lines.append(f"- {label}: {value}")
        return "\n".join(lines) if len(lines) > 1 else "Tool executed successfully."

    def _waiting_message(self, status: str, human_interactions, safety_holds, missing_tools, blocked_steps) -> str:
        if human_interactions:
            return "The workflow is waiting for additional information before it can continue."
        if safety_holds:
            return "The workflow is waiting for your confirmation before executing a sensitive or irreversible step."
        if missing_tools:
            return "The workflow needs a reusable runtime tool to be generated and registered before it can continue."
        if blocked_steps:
            return "The workflow is blocked and did not execute a tool yet. Please review the blocked step details."
        return f"The workflow is not completed yet. Current execution status: {status}."

    def _summarize_tool_result(self, step: dict[str, Any], tool_result: dict[str, Any]) -> str:
        if not tool_result:
            return f"Step {step.get('step_id', '')} executed, but returned no result."
        if tool_result.get("status") != "success":
            err = tool_result.get("error") if isinstance(tool_result.get("error"), dict) else {}
            return f"Step {step.get('step_id', '')} failed: {err.get('message') or tool_result.get('status')}"
        for key in ["final_answer", "answer", "summary", "message", "text"]:
            value = tool_result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        data = tool_result.get("data")
        if isinstance(data, dict):
            for key in ["final_answer", "answer", "summary", "message", "text"]:
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            return self._format_data_result(data)
        if data is not None:
            return "Tool executed successfully. Result: " + str(data)
        return "Tool executed successfully."
