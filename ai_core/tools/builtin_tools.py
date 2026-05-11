from __future__ import annotations
from datetime import date, timedelta

class WeatherForecastTool:
    name = "weather_forecast"
    async def run(self, args: dict) -> dict:
        location = args.get("location", "Tokyo")
        d = args.get("date", "tomorrow")
        target = (date.today() + timedelta(days=1)).isoformat() if d == "tomorrow" else d
        return {
            "tool": self.name,
            "location": location,
            "date": target,
            "summary": f"{location} {target}: cloudy with possible light rain, 18-24°C (mock forecast)",
            "source": "mock_weather_runtime_tool",
        }

class FlightBookingTool:
    name = "flight_booking"
    async def run(self, args: dict) -> dict:
        return {
            "tool": self.name,
            "status": "approval_required",
            "summary": "真实订票前需要人工确认。已生成预订草案：destination=Tokyo, cabin=economy, passenger=current_user。",
            "booking_draft": {
                "destination": args.get("destination", "Tokyo"),
                "cabin": args.get("cabin", "economy"),
                "status": "draft_only",
            },
        }

class WebSearchTool:
    name = "web_search"
    async def run(self, args: dict) -> dict:
        return {"tool": self.name, "summary": "mock web search result", "query": args.get("query")}
