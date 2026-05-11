from __future__ import annotations

import json
from typing import Any

from ai_core.bootstrap.runtime_bootstrap import RuntimeBootstrap
from ai_core.config.io import read_yaml
from ai_core.config.paths import RUNTIME_WORKFLOWS_DIR
from ai_core.evolution.external_reviewer import ExternalReviewer
from ai_core.evolution.runtime_config_generator import RuntimeConfigGenerator
from ai_core.knowledge.knowledge_service import KnowledgeService
from ai_core.llm.model_router import ModelRouter
from ai_core.memory.memory_manager import MemoryManager
from ai_core.orchestration.prompts import prompt_for_step
from ai_core.orchestration.trace import TraceRecorder
from ai_core.security.approval_service import ApprovalService
from ai_core.tools.tool_executor import ToolExecutor
from ai_core.validation.step_validator import StepValidator


class VerifiedOrchestrationEngine:
    BASE_STEPS = [
        "input_parsing",
        "intent_recognition",
        "context_awareness",
        "workflow_planning",
        "execution",
        "feedback_learning",
        "output",
    ]

    def __init__(self) -> None:
        RuntimeBootstrap().ensure_runtime_base()
        self.generator = RuntimeConfigGenerator()
        self.generator.ensure_basic_orchestration()
        self.router = ModelRouter()
        self.router.ensure_default_routes()
        self.knowledge = KnowledgeService()
        self.memory = MemoryManager()
        self.tools = ToolExecutor()
        self.validator = StepValidator()
        self.reviewer = ExternalReviewer()
        self.approval = ApprovalService()

    async def run(self, user_text: str, interactive: bool = False, human_feedback: dict[str, Any] | None = None) -> dict[str, Any]:
        trace = TraceRecorder()
        state: dict[str, Any] = {"user_text": user_text, "human_feedback": human_feedback or {}, "step_results": {}}
        self.memory.add_message("user", user_text)

        method = self.knowledge.find_similar_method(user_text)
        if method:
            state["knowledge_method"] = method
            trace.add("knowledge_lookup", "hit", method)
        else:
            trace.add("knowledge_lookup", "miss", {})

        for step in self.BASE_STEPS:
            if step == "execution":
                result = await self._execute_tools(state, trace, interactive)
            elif step == "output":
                result = self._build_output(state)
            else:
                result = await self._verified_llm_step(step, user_text, state, trace, interactive)
            state["step_results"][step] = result
            trace.add(step, "completed", {"result": result})

        final_answer = state["step_results"].get("output", {}).get("final_answer", "")
        self.memory.add_message("assistant", final_answer)
        state["final_answer"] = final_answer
        state["trace_id"] = trace.trace_id
        case_path = self.knowledge.save_success_case(user_text, state)
        trace.add("knowledge_save", "saved", {"path": str(case_path)})
        trace_file = trace.save()
        state["trace_file"] = trace_file
        return state

    async def _verified_llm_step(self, step: str, user_text: str, state: dict[str, Any], trace: TraceRecorder, interactive: bool) -> dict[str, Any]:
        prompt = prompt_for_step(step, user_text, state)
        self.generator.save_prompt(step, prompt)
        llm_result = await self.router.generate_with_route(step, prompt, user_text=user_text)
        parsed = self._parse_json_or_text(llm_result.text)
        if step == "intent_recognition" and isinstance(parsed, dict):
            self.generator.save_intent_config(parsed)
        if step == "workflow_planning" and isinstance(parsed, dict):
            self.generator.save_workflow(parsed)

        validation = self.validator.validate(step, parsed if isinstance(parsed, dict) else {"text": parsed})
        trace.add(step, "local_result", {"provider": llm_result.provider, "model": llm_result.model, "result": parsed, "validation": validation})

        human_ok = self._human_review(step, parsed, validation, interactive, state)
        trace.add(step, "human_review", human_ok)
        if validation["passed"] and human_ok.get("accepted", True):
            return {"result": parsed, "provider": llm_result.provider, "model": llm_result.model, "validated": True}

        review = await self.reviewer.review_failure(step, user_text, parsed, validation)
        trace.add(step, "external_review", review)
        improved = review.get("improved_result") or {}
        if improved:
            parsed = improved
        return {"result": parsed, "provider": "external_review_or_local", "review": review, "validated": bool(improved)}

    def _human_review(self, step: str, result: Any, validation: dict[str, Any], interactive: bool, state: dict[str, Any]) -> dict[str, Any]:
        feedback = state.get("human_feedback", {}).get(step)
        if feedback:
            return {"accepted": bool(feedback.get("accepted")), "feedback": feedback}
        if not interactive:
            return {"accepted": validation.get("passed", False), "mode": "auto_non_interactive"}
        print(f"\n--- Human review: {step} ---")
        print(json.dumps(result, ensure_ascii=False, indent=2) if isinstance(result, dict) else result)
        ans = input("Accept? y/N: ").strip().lower()
        return {"accepted": ans == "y", "mode": "interactive"}

    async def _execute_tools(self, state: dict[str, Any], trace: TraceRecorder, interactive: bool) -> dict[str, Any]:
        intent = state["step_results"].get("intent_recognition", {}).get("result", {})
        if not isinstance(intent, dict):
            return {"ok": False, "error": "intent_not_structured"}
        outputs = []
        for task in intent.get("tasks", []):
            if task.get("type") == "weather_check":
                res = await self.tools.execute("weather_forecast", {"location": task.get("location"), "date": task.get("date")})
                outputs.append(res)
            elif task.get("type") == "flight_booking":
                search = await self.tools.execute("flight_search", {"destination": task.get("destination")})
                outputs.append(search)
                approval = self.approval.request_approval("book_flight", search, interactive=interactive)
                trace.add("approval", "checked", approval)
                booking = await self.tools.execute("flight_booking_mock", {"approved": approval.get("approved")})
                outputs.append(booking)
        return {"ok": True, "tool_outputs": outputs}

    def _build_output(self, state: dict[str, Any]) -> dict[str, Any]:
        execution = state["step_results"].get("execution", {})
        tool_outputs = execution.get("tool_outputs", []) if isinstance(execution, dict) else []
        weather = next((x for x in tool_outputs if x.get("tool") == "weather_forecast"), None)
        flight = next((x for x in tool_outputs if x.get("tool") == "flight_search"), None)
        booking = next((x for x in tool_outputs if x.get("booking_id") or x.get("requires_approval")), None)
        parts = []
        if weather:
            parts.append(f"Tokyo weather for {weather.get('date')}: {weather.get('forecast')}, {weather.get('temperature_c')}°C.")
        if flight:
            if flight.get("needs_more_info"):
                parts.append("To search/book a flight to Tokyo, I still need: " + ", ".join(flight.get("missing_fields", [])) + ".")
            else:
                parts.append("Flight options were found.")
        if booking:
            parts.append(booking.get("message", "Booking step completed."))
        if not parts:
            parts.append("The request was processed, but no executable tool result was produced.")
        return {"final_answer": " ".join(parts), "tool_outputs": tool_outputs}

    def _parse_json_or_text(self, text: str) -> Any:
        try:
            t = text.strip()
            if t.startswith("```"):
                t = t.strip("`").replace("json", "", 1).strip()
            return json.loads(t)
        except Exception:
            return {"text": text}
