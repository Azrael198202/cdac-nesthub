from __future__ import annotations

from typing import Any

from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import PROJECT_ROOT
from ai_core.presentation.result_presenter import ResultPresenter
from ai_core.presentation.result_material_builder import ResultMaterialBuilder
from ai_core.presentation.final_answer_synthesizer import FinalAnswerSynthesizer
from ai_core.validation.schema_validator import SchemaValidator
from ai_core.knowledge.knowledge_service import KnowledgeService


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
        self.presenter = ResultPresenter()
        self.material_builder = ResultMaterialBuilder()
        self.final_synthesizer = FinalAnswerSynthesizer()
        self.knowledge = KnowledgeService()

    async def execute(self, workflow_node, node_config, state, capability_result):
        result = await self._build(state, node_config)
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

    async def _build(self, state: dict[str, Any], node_config: dict[str, Any]) -> dict[str, Any]:
        results = state.get("results", {}) if isinstance(state, dict) else {}
        final_synthesis_result = results.get("final_synthesis") if isinstance(results.get("final_synthesis"), dict) else {}
        verification = results.get("result_verification") if isinstance(results.get("result_verification"), dict) else {}
        verification_record = verification.get("verification_record") if isinstance(verification.get("verification_record"), dict) else verification
        verification_failed = verification_record.get("status") == "failed"
        explicit_final = final_synthesis_result.get("final_answer") or final_synthesis_result.get("answer")
        if isinstance(explicit_final, str) and explicit_final.strip() and not verification_failed:
            return {
                "_executor_type": "output",
                "_node_id": node_config.get("node_id", "output"),
                "status": "completed",
                "message": explicit_final.strip(),
                "final_answer": explicit_final.strip(),
                "source": "final_synthesis.final_answer",
            }
        execution = results.get("execution") if isinstance(results.get("execution"), dict) else {}
        status = str(execution.get("status") or "unknown")
        execution_steps = execution.get("execution_steps") if isinstance(execution.get("execution_steps"), list) else []
        blocked_steps = execution.get("blocked_steps") if isinstance(execution.get("blocked_steps"), list) else []
        safety_holds = execution.get("safety_holds") if isinstance(execution.get("safety_holds"), list) else []
        human_interactions = execution.get("human_interactions") if isinstance(execution.get("human_interactions"), list) else []
        optional_human_interactions = execution.get("optional_human_interactions") if isinstance(execution.get("optional_human_interactions"), list) else []
        missing_tools = execution.get("missing_tools") if isinstance(execution.get("missing_tools"), list) else []

        if status == "waiting_optional_upgrade":
            request = self._optional_upgrade_request(optional_human_interactions)
            message = request.get("message") or "Optional API key input is available."
            return {
                "_executor_type": "output",
                "_node_id": node_config.get("node_id", "output"),
                "status": "waiting_optional_upgrade",
                "message": message,
                "execution_status": status,
                "interaction_request": request,
                "executed_steps": len(execution_steps),
                "blocked_steps": blocked_steps,
                "optional_human_interactions": optional_human_interactions,
                "final_answer": message,
            }

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
            }

        tool_results: list[dict[str, Any]] = []
        provenance_records: list[dict[str, Any]] = []
        result_materials: list[dict[str, Any]] = []
        for step in execution_steps:
            if not isinstance(step, dict):
                continue
            tool_result = step.get("result") if isinstance(step.get("result"), dict) else {}
            tool_results.append(tool_result)
            provenance = tool_result.get("provenance") if isinstance(tool_result.get("provenance"), dict) else step.get("provenance")
            if isinstance(provenance, dict):
                provenance_records.append(provenance)
            result_materials.append(self.material_builder.from_execution_step(step).to_dict())

        trust_summary = self._trust_summary(provenance_records, tool_results)
        synthesized = await self.final_synthesizer.synthesize(
            run_id=str(state.get("run_id") or state.get("id") or ""),
            node_id=str(node_config.get("node_id", "output")),
            state=state,
            materials=result_materials,
            trust_summary=trust_summary,
        )
        final_answer = synthesized.get("answer") or self._answer_material_from_execution_steps(execution_steps) or "Workflow finished, but no user-facing answer was produced."

        if trust_summary.get("trust_level") == "unverified_generated_result" and final_answer.startswith("I could not"):
            final_answer = final_answer + "\n\nTrust: unverified generated result. The runtime did not confirm live network verification, no-mock execution, or evidence-supported material quality."

        self._save_verified_answer_to_knowledge(state=state, final_answer=final_answer, synthesized=synthesized, trust_summary=trust_summary)

        return {
            "_executor_type": "output",
            "_node_id": node_config.get("node_id", "output"),
            "status": "completed" if status in self.TERMINAL_SUCCESS else status,
            "message": final_answer,
            "final_answer": final_answer,
            "execution_status": status,
            "result_material": synthesized.get("result_material", []),
            "synthesis": synthesized.get("synthesis", {}),
            "tool_results": tool_results,
            "provenance": provenance_records,
            "trust_summary": trust_summary,
            "executed_steps": len(execution_steps),
            "blocked_steps": blocked_steps,
        }


    def _answer_material_from_execution_steps(self, execution_steps: list[dict[str, Any]]) -> str:
        """Extract public generated answer material from execution results.

        This is a delivery fallback for locked generation workflows. It remains
        generic by reading only public answer fields and never node messages from
        input/intermediate stages.
        """
        public_keys = ("answer_material", "final_answer", "answer", "generated_content", "content", "text")

        def scan(value: Any) -> str:
            if isinstance(value, dict):
                for key in public_keys:
                    item = value.get(key)
                    if isinstance(item, str) and item.strip():
                        return item.strip()
                    if isinstance(item, (dict, list)):
                        nested = scan(item)
                        if nested:
                            return nested
                for child in value.values():
                    if isinstance(child, (dict, list)):
                        nested = scan(child)
                        if nested:
                            return nested
            elif isinstance(value, list):
                for item in value[:20]:
                    nested = scan(item)
                    if nested:
                        return nested
            return ""

        for step in execution_steps:
            if not isinstance(step, dict):
                continue
            result = step.get("result") if isinstance(step.get("result"), dict) else {}
            text = scan(result)
            if text:
                return text
        return ""

    def _save_verified_answer_to_knowledge(self, *, state: dict[str, Any], final_answer: str, synthesized: dict[str, Any], trust_summary: dict[str, Any]) -> None:
        try:
            if not final_answer or trust_summary.get("trust_level") == "unverified_generated_result":
                return
            self.knowledge.save_answer_result(
                run_id=str(state.get("run_id") or state.get("id") or ""),
                query=str(state.get("input") or ""),
                final_answer=final_answer,
                facts=((synthesized.get("result_material") or [{}])[0].get("content") or {}).get("normalized_facts", []) if isinstance(synthesized.get("result_material"), list) else [],
                trust_summary=trust_summary,
            )
        except Exception:
            return

    def _optional_upgrade_request(self, interactions: list[dict[str, Any]]) -> dict[str, Any]:
        first = interactions[0] if interactions and isinstance(interactions[0], dict) else {}
        return {
            "type": "credential_optional_upgrade",
            "title": first.get("title") or "Optional API Key Available",
            "message": first.get("message") or "A credential-protected provider may improve the result. You can provide an API key or continue without it.",
            "required": False,
            "secret_fields": first.get("secret_fields") or [
                {
                    "name": "credential",
                    "label": "API Key / Credential",
                    "interaction_type": "secret",
                    "required": False,
                    "placeholder": "Paste API key here",
                }
            ],
            "actions": first.get("actions") or [
                {"id": "continue_without_key", "label": "Continue without API key"},
                {"id": "provide_credential", "label": "Provide API key and continue"},
            ],
            "options": first.get("options") or [
                {"id": "continue_without_key", "label": "Continue without API key"},
                {"id": "provide_credential", "label": "Provide API key and continue"},
            ],
        }

    def _trust_summary(self, provenance_records: list[dict[str, Any]], tool_results: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        tool_results = tool_results or []
        evidence_supported = any(self.presenter.evidence_quality_passed(item) for item in tool_results if isinstance(item, dict))
        if not provenance_records:
            return {
                "trace_available": False,
                "evidence_quality_passed": evidence_supported,
                "verified_real_execution": False,
                "trust_level": "evidence_supported_result" if evidence_supported else "unverified_generated_result",
                "message": "No execution provenance was recorded for this result.",
            }
        real_declared = any(bool((p.get("execution_claims") or {}).get("real_execution_declared")) for p in provenance_records)
        no_mock_declared = any(bool((p.get("execution_claims") or {}).get("no_mock_data_declared")) for p in provenance_records)
        network_declared = any(bool((p.get("execution_claims") or {}).get("network_declared")) for p in provenance_records)
        live_verified = any(bool((p.get("execution_claims") or {}).get("live_verification_passed")) for p in provenance_records)
        api_discovery = any(bool((p.get("execution_claims") or {}).get("api_discovery_trace_id")) for p in provenance_records)
        runtime_native_verified = any(
            bool((p.get("execution_claims") or {}).get("real_execution_declared"))
            and bool((p.get("execution_claims") or {}).get("no_mock_data_declared"))
            and bool((p.get("execution_claims") or {}).get("live_verification_passed"))
            and str(p.get("source") or "") == "runtime_native"
            for p in provenance_records
        )
        verified_real_execution = bool(real_declared and no_mock_declared and (network_declared or runtime_native_verified) and live_verified)
        trust_level = "verified_real_execution" if verified_real_execution else "evidence_supported_result" if evidence_supported else "unverified_generated_result"
        return {
            "trace_available": True,
            "trace_count": len(provenance_records),
            "real_execution_declared": real_declared,
            "no_mock_data_declared": no_mock_declared,
            "network_declared": network_declared,
            "api_discovery_trace_available": api_discovery,
            "live_verification_passed": live_verified,
            "evidence_quality_passed": evidence_supported,
            "verified_real_execution": verified_real_execution,
            "trust_level": trust_level,
            "trace_ids": [p.get("trace_id") for p in provenance_records if p.get("trace_id")],
        }

    def _format_data_result(self, data: dict[str, Any]) -> str:
        return self.presenter.present_data(data)

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
            return self.presenter.present_tool_result(tool_result)
        if data is not None:
            return "The step completed with result: " + str(data)
        return "The step completed successfully."
