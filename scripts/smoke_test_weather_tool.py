import asyncio
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_core.config.paths import RUNTIME_DIR

if RUNTIME_DIR.exists():
    shutil.rmtree(RUNTIME_DIR)

from ai_core.runtime.bootstrap import RuntimeBootstrap
from ai_core.executors.tool_call_executor import ToolCallExecutor


# This artifact represents code produced by the runtime intelligence layer
# from a generic capability request. It is intentionally NOT inside ai_core.
# ai_core never knows this provider name or endpoint; it only installs,
# validates, registers, and executes this artifact.
GENERATED_WEATHER_TOOL_CODE = r'''
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_RETRY_COUNT = 2


def run(input_data: dict[str, Any]) -> dict[str, Any]:
    parameters = input_data.get("parameters", {}) if isinstance(input_data, dict) else {}
    known = parameters.get("known", {}) if isinstance(parameters, dict) else {}
    location = _first_text(known.get("location"), parameters.get("location"), input_data.get("location"))
    target_date_text = _first_text(known.get("date"), parameters.get("date"), input_data.get("date")) or "today"
    if not location:
        return _error("missing_location", "location is required.")

    timeout = _positive_float(input_data.get("timeout_seconds"), DEFAULT_TIMEOUT_SECONDS)
    retries = _non_negative_int(input_data.get("retry_count"), DEFAULT_RETRY_COUNT)

    try:
        target_date = _resolve_date(target_date_text)
        geo = _geocode(location, timeout=timeout, retries=retries)
        forecast = _forecast(geo["latitude"], geo["longitude"], target_date, geo.get("timezone") or "auto", timeout, retries)
        daily = forecast.get("daily") or {}
        times = daily.get("time") or []
        if target_date.isoformat() not in times:
            raise RuntimeError(f"Forecast date not available: {target_date.isoformat()}")
        idx = times.index(target_date.isoformat())
        code = _safe_index(daily.get("weather_code"), idx)
        data = {
            "location": {
                "query": location,
                "name": geo.get("name"),
                "country": geo.get("country"),
                "admin1": geo.get("admin1"),
                "latitude": geo.get("latitude"),
                "longitude": geo.get("longitude"),
                "timezone": geo.get("timezone"),
            },
            "date": target_date.isoformat(),
            "forecast": {
                "weather_code": code,
                "weather_label": _weather_label(code),
                "temperature_max": _safe_index(daily.get("temperature_2m_max"), idx),
                "temperature_min": _safe_index(daily.get("temperature_2m_min"), idx),
                "precipitation_probability_max": _safe_index(daily.get("precipitation_probability_max"), idx),
                "precipitation_sum": _safe_index(daily.get("precipitation_sum"), idx),
                "wind_speed_max": _safe_index(daily.get("wind_speed_10m_max"), idx),
            },
            "units": forecast.get("daily_units", {}),
            "network": {"real_api_called": True, "retry_count": retries, "timeout_seconds": timeout},
        }
        return {
            "status": "success",
            "data": data,
            "source": "runtime_generated_tool",
            "requires_human_confirmation": False,
            "summary": _summary(data),
        }
    except Exception as exc:
        return _error("weather_api_failed", str(exc))


def _geocode(location: str, timeout: float, retries: int) -> dict[str, Any]:
    url = GEOCODE_URL + "?" + urlencode({"name": location, "count": 1, "language": "en", "format": "json"})
    data = _get_json_with_retry(url, timeout=timeout, retries=retries)
    results = data.get("results") or []
    if not results:
        raise RuntimeError(f"Location not found: {location}")
    return results[0]


def _forecast(latitude: float, longitude: float, target_date: date, timezone: str, timeout: float, retries: int) -> dict[str, Any]:
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": ",".join([
            "weather_code",
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_probability_max",
            "precipitation_sum",
            "wind_speed_10m_max",
        ]),
        "timezone": timezone,
        "start_date": target_date.isoformat(),
        "end_date": target_date.isoformat(),
    }
    return _get_json_with_retry(FORECAST_URL + "?" + urlencode(params), timeout=timeout, retries=retries)


def _get_json_with_retry(url: str, timeout: float, retries: int) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = Request(url, headers={"User-Agent": "runtime-generated-tool/1.0"})
            with urlopen(req, timeout=timeout) as response:
                if response.status >= 400:
                    raise RuntimeError(f"HTTP {response.status}")
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
            last_error = exc
            if attempt >= retries:
                break
            time.sleep(min(2 ** attempt, 3))
    raise RuntimeError(f"HTTP request failed after {retries + 1} attempts: {last_error}")


def _resolve_date(value: str) -> date:
    text = str(value or "today").strip().lower()
    today = date.today()
    if text in {"today", "now"}:
        return today
    if text == "tomorrow":
        return today + timedelta(days=1)
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise RuntimeError(f"Unsupported date value: {value}. Use today, tomorrow, or YYYY-MM-DD.")


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _positive_float(value: Any, default: float) -> float:
    try:
        number = float(value)
        return number if number > 0 else default
    except (TypeError, ValueError):
        return default


def _non_negative_int(value: Any, default: int) -> int:
    try:
        number = int(value)
        return number if number >= 0 else default
    except (TypeError, ValueError):
        return default


def _safe_index(values: Any, index: int) -> Any:
    if isinstance(values, list) and 0 <= index < len(values):
        return values[index]
    return None


def _weather_label(code: Any) -> str:
    labels = {
        0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
        45: "fog", 48: "depositing rime fog", 51: "light drizzle", 53: "moderate drizzle",
        55: "dense drizzle", 61: "slight rain", 63: "moderate rain", 65: "heavy rain",
        71: "slight snow", 73: "moderate snow", 75: "heavy snow",
        80: "slight rain showers", 81: "moderate rain showers", 82: "violent rain showers",
        95: "thunderstorm",
    }
    return labels.get(code, "unknown")


def _summary(data: dict[str, Any]) -> str:
    loc = data.get("location", {}).get("name") or data.get("location", {}).get("query")
    fc = data.get("forecast", {})
    return f"{loc} {data.get('date')}: {fc.get('weather_label')}, high {fc.get('temperature_max')}°C, low {fc.get('temperature_min')}°C."


def _error(code: str, message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "error": {"code": code, "message": message},
        "data": {},
        "source": "runtime_generated_tool",
        "requires_human_confirmation": False,
    }
'''


async def main() -> None:
    if os.getenv("RUN_REAL_NETWORK_TEST") != "1":
        raise SystemExit(
            "This is a real network integration test. Set RUN_REAL_NETWORK_TEST=1 to execute it. "
            "No mock path exists in this test."
        )

    RuntimeBootstrap().ensure()
    state = {
        "run_id": "weather-real-integration",
        "input": "Please check the weather forecast for Tokyo tomorrow.",
        "results": {
            "workflow_planning": {
                "planned_steps": [
                    {
                        "task_id": "1",
                        "task_type": "weather.forecast.query",
                        "action": "check_weather_forecast",
                        "parameters": {
                            "known": {"location": "Tokyo", "date": "tomorrow"},
                            "missing_required": {},
                            "optional": {},
                        },
                        "depends_on": [],
                        "requires_human_confirmation": False,
                        "execution_ready": True,
                        "required_capability": "weather_api",
                        "runtime_tool_generation": {
                            "tool_id": "runtime_generated_weather_tool",
                            "manifest": {
                                "name": "Runtime Generated Weather Tool",
                                "capability": "weather_api",
                                "capabilities": ["weather_api"],
                                "status": "enabled",
                                "implementation": {"type": "python_function", "module_path": "tool.py", "function": "run"},
                                "input_schema": {"type": "object", "required": ["parameters"], "properties": {"parameters": {"type": "object"}}, "additionalProperties": True},
                                "output_schema": {"type": "object", "required": ["status", "data", "source", "requires_human_confirmation"], "properties": {"status": {"type": "string"}, "data": {"type": "object"}, "source": {"type": "string"}, "requires_human_confirmation": {"type": "boolean"}}, "additionalProperties": True},
                                "safety": {
                                    "can_read_external_data": True,
                                    "can_write_external_data": False,
                                    "can_perform_irreversible_action": False,
                                    "requires_human_confirmation": False,
                                    "network_access": "https_get_only"
                                }
                            },
                            "files": {"tool.py": GENERATED_WEATHER_TOOL_CODE},
                            "auto_register": True
                        }
                    }
                ],
                "required_capabilities": ["weather_api"],
            }
        },
    }
    result = await ToolCallExecutor().execute({"id": "execution"}, {"node_id": "execution"}, state, {})
    assert result["status"] == "executed", result
    tool_result = result["execution_steps"][0]["result"]
    assert tool_result["status"] == "success", result
    assert tool_result["data"]["location"]["query"] == "Tokyo", result
    assert tool_result["data"]["network"]["real_api_called"] is True, result
    assert result["execution_steps"][0]["tool"]["runtime_generated"] is True, result
    print("weather real integration ok:", tool_result.get("summary"))


asyncio.run(main())
