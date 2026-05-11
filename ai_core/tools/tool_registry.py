from __future__ import annotations
from ai_core.tools.builtin_tools import WeatherForecastTool, FlightBookingTool, WebSearchTool

class ToolRegistry:
    def __init__(self):
        self.tools = {
            "weather_forecast": WeatherForecastTool(),
            "flight_booking": FlightBookingTool(),
            "web_search": WebSearchTool(),
        }

    def get(self, name: str):
        if name not in self.tools:
            raise KeyError(f"Tool not registered: {name}")
        return self.tools[name]
