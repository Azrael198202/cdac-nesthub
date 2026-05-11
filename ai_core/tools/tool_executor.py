from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ai_core.tools.tool_registry import ToolRegistry


class ToolExecutor:
    def __init__(self) -> None:
        self.registry = ToolRegistry()

    async def execute(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        self.registry.ensure_default_tools()
        if name == "weather_forecast":
            return await self._weather(args)
        if name == "flight_search":
            return await self._flight_search(args)
        if name == "flight_booking_mock":
            return await self._flight_booking_mock(args)
        if name == "web_search":
            return {"ok": True, "results": [], "note": "web_search placeholder. Register real API in runtime/configs/tools/tools.yaml"}
        return {"ok": False, "error": f"unknown_tool:{name}"}

    async def _weather(self, args: dict[str, Any]) -> dict[str, Any]:
        location = args.get("location") or "Tokyo"
        date_text = args.get("date") or "tomorrow"
        date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d") if date_text == "tomorrow" else date_text
        # Mock by default. Runtime tool config can replace with real weather API without changing ai_core.
        return {"ok": True, "tool": "weather_forecast", "location": location, "date": date, "forecast": "Partly cloudy", "temperature_c": "18-24", "source": "mock_runtime_builtin"}

    async def _flight_search(self, args: dict[str, Any]) -> dict[str, Any]:
        destination = args.get("destination") or "Tokyo"
        departure_city = args.get("departure_city") or "UNKNOWN_DEPARTURE_CITY"
        travel_date = args.get("travel_date") or "UNKNOWN_TRAVEL_DATE"
        needs_info = departure_city.startswith("UNKNOWN") or travel_date.startswith("UNKNOWN")
        return {
            "ok": True,
            "tool": "flight_search",
            "needs_more_info": needs_info,
            "missing_fields": [f for f, v in {"departure_city": departure_city, "travel_date": travel_date}.items() if str(v).startswith("UNKNOWN")],
            "options": [] if needs_info else [{"flight_no": "MOCK123", "from": departure_city, "to": destination, "date": travel_date, "price": "mock"}],
        }

    async def _flight_booking_mock(self, args: dict[str, Any]) -> dict[str, Any]:
        if not args.get("approved"):
            return {"ok": False, "requires_approval": True, "message": "Booking requires human approval."}
        return {"ok": True, "booking_id": "MOCK-BOOKING-001", "message": "Mock booking created. No real payment or reservation was made."}
