from __future__ import annotations
import os, json
import httpx
from ai_core.config_loader import ConfigLoader

class ModelRouter:
    def __init__(self):
        self.loader = ConfigLoader()
        self.config = self.loader.load_yaml("models/model_router.yaml")

    async def generate_json(self, task: str, prompt: str, user_input: str) -> dict:
        group = self.config.get("task_routes", {}).get(task, "rule_model")
        model_cfg = self.config.get("models", {}).get(group, {})
        provider = model_cfg.get("provider", "rule")
        if provider == "openai" and os.getenv("OPENAI_API_KEY"):
            return await self._openai_json(model_cfg, prompt, user_input)
        return self._rule_json(task, user_input)

    async def generate_text(self, task: str, prompt: str, user_input: str, context: dict | None = None) -> str:
        group = self.config.get("task_routes", {}).get(task, "rule_model")
        model_cfg = self.config.get("models", {}).get(group, {})
        provider = model_cfg.get("provider", "rule")
        if provider == "openai" and os.getenv("OPENAI_API_KEY"):
            return await self._openai_text(model_cfg, prompt, user_input, context or {})
        return self._rule_text(task, user_input, context or {})

    async def _openai_json(self, model_cfg: dict, prompt: str, user_input: str) -> dict:
        body = {
            "model": model_cfg.get("model", "gpt-4o-mini"),
            "messages": [
                {"role": "system", "content": prompt + "\nReturn only JSON."},
                {"role": "user", "content": user_input},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        async with httpx.AsyncClient(timeout=60) as client:
            res = await client.post("https://api.openai.com/v1/chat/completions", headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}"}, json=body)
            res.raise_for_status()
            return json.loads(res.json()["choices"][0]["message"]["content"])

    async def _openai_text(self, model_cfg: dict, prompt: str, user_input: str, context: dict) -> str:
        body = {
            "model": model_cfg.get("model", "gpt-4o-mini"),
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_input + "\n\nContext:\n" + json.dumps(context, ensure_ascii=False)},
            ],
            "temperature": 0.2,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            res = await client.post("https://api.openai.com/v1/chat/completions", headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}"}, json=body)
            res.raise_for_status()
            return res.json()["choices"][0]["message"]["content"]

    def _rule_json(self, task: str, user_input: str) -> dict:
        text = user_input.lower()
        if task == "intent_recognition":
            intents = []
            if "weather" in text or "forecast" in text:
                intents.append({"name": "weather_forecast", "confidence": 0.95, "slots": {"location": "Tokyo", "date": "tomorrow"}})
            if "flight" in text or "book" in text:
                intents.append({"name": "flight_booking", "confidence": 0.91, "slots": {"destination": "Tokyo"}})
            return {"primary_intent": "multi_step_travel_assistant", "confidence": 0.93, "intents": intents}
        if task == "workflow_planning":
            return {"steps": [
                {"id": "check_weather", "tool": "weather_forecast", "args": {"location": "Tokyo", "date": "tomorrow"}},
                {"id": "book_flight", "tool": "flight_booking", "args": {"destination": "Tokyo"}, "approval_required": True},
            ]}
        return {}

    def _rule_text(self, task: str, user_input: str, context: dict) -> str:
        if task == "final_response":
            weather = next((r for r in context.get("tool_results", []) if r.get("tool") == "weather_forecast"), {})
            flight = next((r for r in context.get("tool_results", []) if r.get("tool") == "flight_booking"), {})
            return f"已完成处理。东京明天天气：{weather.get('summary','未取得')}。机票预订结果：{flight.get('summary','需要人工确认后才能提交真实预订')}。"
        return "Done."
