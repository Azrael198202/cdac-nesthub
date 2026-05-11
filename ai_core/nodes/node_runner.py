import re
from typing import Dict, Any


class NodeRunner:
    async def run(self, node: Dict[str, Any], state: Dict[str, Any], capability: Dict[str, Any]) -> Dict[str, Any]:
        node_type = node.get("type")
        if node_type == "input_parsing":
            return self._input_parsing(state.get("input", ""))
        if node_type == "intent_recognition":
            return self._intent_recognition(state)
        if node_type == "context_awareness":
            return self._context_awareness(state)
        if node_type == "workflow_planning":
            return self._workflow_planning(state)
        if node_type == "execution":
            return self._execution_plan(state)
        if node_type == "feedback_learning":
            return self._feedback_learning(state)
        if node_type == "output":
            return self._output(state)
        return {"status": "unknown_node_type", "node_type": node_type}

    def _input_parsing(self, text: str) -> Dict[str, Any]:
        lower = text.lower()
        tasks = []
        required = []
        missing = []

        if any(k in lower for k in ["weather", "forecast", "temperature", "rain"]):
            location = self._extract_after_keywords(text, ["in", "for"]) or self._extract_capitalized_place(text)
            date = "tomorrow" if "tomorrow" in lower else None
            tasks.append({
                "task_id": "task_weather_forecast",
                "task_type": "weather_forecast",
                "location": location,
                "date": date
            })
            required.append("weather_query_tool")
            if not location:
                missing.append("weather location")
            if not date:
                missing.append("weather date")

        if any(k in lower for k in ["flight", "book a flight", "air ticket", "ticket"]):
            destination = self._extract_destination(text)
            tasks.append({
                "task_id": "task_flight_search_or_booking",
                "task_type": "flight_search_or_booking",
                "destination": destination,
                "requires_final_booking_approval": True
            })
            required.append("travel_search_tool")
            required.append("booking_confirmation")
            for item in ["departure city", "travel date", "passenger information", "final booking approval"]:
                missing.append(item)

        if not tasks:
            tasks.append({
                "task_id": "task_general_request",
                "task_type": "general_request",
                "description": text
            })
            required.append("text_understanding")

        return {
            "stage": "input_parsing",
            "original_input": text,
            "language": "en" if re.search(r"[A-Za-z]", text) else "unknown",
            "intent_type": "multi_step_agent_task" if len(tasks) > 1 else tasks[0]["task_type"],
            "tasks": tasks,
            "missing_information": sorted(set(missing)),
            "required_capabilities": sorted(set(required)),
            "safety_notes": [
                "Do not perform final booking or payment without explicit human confirmation."
            ]
        }

    def _intent_recognition(self, state: Dict[str, Any]) -> Dict[str, Any]:
        parsed = state.get("results", {}).get("input_parsing", {})
        return {
            "stage": "intent_recognition",
            "intent_type": parsed.get("intent_type", "unknown"),
            "confidence": 0.82 if parsed.get("tasks") else 0.35,
            "tasks": parsed.get("tasks", []),
            "requires_human_review": True,
            "reason": "Intent is derived from structured input parsing result."
        }

    def _context_awareness(self, state: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "stage": "context_awareness",
            "short_term_context_used": True,
            "knowledge_hits": [],
            "notes": "No existing runtime knowledge matched this request."
        }

    def _workflow_planning(self, state: Dict[str, Any]) -> Dict[str, Any]:
        parsed = state.get("results", {}).get("input_parsing", {})
        steps = []
        for task in parsed.get("tasks", []):
            steps.append({
                "step_id": f"step_{len(steps)+1}",
                "task_type": task.get("task_type"),
                "action": "prepare_required_capability_and_execute",
                "requires_human_confirmation": task.get("requires_final_booking_approval", False)
            })
        return {
            "stage": "workflow_planning",
            "planned_steps": steps,
            "blocking_missing_information": parsed.get("missing_information", [])
        }

    def _execution_plan(self, state: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "stage": "execution",
            "status": "waiting_for_missing_information_or_tools",
            "message": "Execution cannot continue until required tools and missing information are resolved.",
            "missing_information": state.get("results", {}).get("input_parsing", {}).get("missing_information", [])
        }

    def _feedback_learning(self, state: Dict[str, Any]) -> Dict[str, Any]:
        return {"stage": "feedback_learning", "saved_to_runtime_trace": True}

    def _output(self, state: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "stage": "output",
            "summary": "Workflow completed up to the available capability boundary.",
            "results": state.get("results", {})
        }

    def _extract_destination(self, text: str):
        m = re.search(r"to\s+([A-Z][A-Za-z\- ]+?)(?:\.|,|$)", text)
        return m.group(1).strip() if m else None

    def _extract_after_keywords(self, text: str, keywords):
        for kw in keywords:
            m = re.search(rf"{kw}\s+([A-Z][A-Za-z\- ]+?)(?:\s+tomorrow|\.|,|$)", text)
            if m:
                return m.group(1).strip()
        return None

    def _extract_capitalized_place(self, text: str):
        words = re.findall(r"\b[A-Z][a-z]+\b", text)
        skip = {"Please"}
        places = [w for w in words if w not in skip]
        return places[-1] if places else None
