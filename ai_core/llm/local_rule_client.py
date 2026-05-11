from __future__ import annotations

import json
import re
from typing import Any

from ai_core.llm.base import BaseLLMClient, LLMResult


class LocalRuleClient(BaseLLMClient):
    """No dependency fallback. Simulates a tiny local model for cold start."""

    def __init__(self, model: str = "local-rule-v1") -> None:
        self.model = model

    async def generate(self, prompt: str, **kwargs: Any) -> LLMResult:
        lower = prompt.lower()
        user_text = kwargs.get("user_text", prompt)
        if "intent recognition" in lower or "classify" in lower:
            text = json.dumps(self._intent(user_text), ensure_ascii=False)
        elif "workflow planning" in lower:
            text = json.dumps(self._workflow(user_text), ensure_ascii=False)
        elif "validate" in lower or "self check" in lower:
            text = json.dumps({"passed": True, "score": 0.72, "issues": [], "recommendation": "human_review"}, ensure_ascii=False)
        else:
            text = "I analyzed the request with the local rule model."
        return LLMResult(text=text, provider="local", model=self.model)

    def _intent(self, text: str) -> dict[str, Any]:
        lower = text.lower()
        tasks = []
        if "weather" in lower or "forecast" in lower:
            loc = "Tokyo" if "tokyo" in lower else None
            date = "tomorrow" if "tomorrow" in lower else "unknown"
            tasks.append({"type": "weather_check", "location": loc, "date": date})
        if "flight" in lower or "book" in lower:
            dest = "Tokyo" if "tokyo" in lower else None
            tasks.append({"type": "flight_booking", "destination": dest, "requires_human_approval": True})
        return {
            "intent_type": "agent_task" if tasks else "general_chat",
            "confidence": 0.76 if tasks else 0.5,
            "tasks": tasks,
            "requires_tools": bool(tasks),
            "requires_human_approval": any(t.get("requires_human_approval") for t in tasks),
        }

    def _workflow(self, text: str) -> dict[str, Any]:
        return {
            "workflow_id": "generated_agent_task_weather_flight",
            "nodes": [
                {"id": "parse_request", "type": "input_parsing"},
                {"id": "check_weather", "type": "tool", "tool": "weather_forecast"},
                {"id": "collect_flight_info", "type": "human_input", "fields": ["departure_city", "travel_date"]},
                {"id": "search_flights", "type": "tool", "tool": "flight_search"},
                {"id": "approve_booking", "type": "approval"},
                {"id": "book_flight", "type": "tool", "tool": "flight_booking_mock"},
                {"id": "save_learning", "type": "feedback_learning"},
            ],
        }
