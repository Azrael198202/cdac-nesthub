from __future__ import annotations

import json
from datetime import timezone, timedelta, tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class RuntimeTimezoneResolver:
    """Resolve runtime timezone identifiers without hard-coded locale fallbacks.

    The operating system or Python distribution may not include the IANA timezone
    database. When that happens, fallback offsets are read from configuration so
    source code remains generic and runtime-configurable.
    """

    def __init__(self, config_path: str | Path = "configs/runtime_timezones.json") -> None:
        self.config_path = Path(config_path)

    def resolve(self, requested: str | None) -> tuple[tzinfo, str, dict[str, Any]]:
        config = self._load_config()
        raw_key = str(requested or config.get("default_timezone") or "UTC").strip() or "UTC"
        key = str((config.get("aliases") or {}).get(raw_key, raw_key))
        try:
            return ZoneInfo(key), key, {"source": "zoneinfo", "fallback_used": False}
        except ZoneInfoNotFoundError:
            offsets = config.get("fallback_offsets_minutes") or {}
            if key in offsets:
                minutes = int(offsets[key])
                return timezone(timedelta(minutes=minutes), name=key), key, {
                    "source": "configured_fixed_offset",
                    "fallback_used": True,
                    "offset_minutes": minutes,
                }
            return datetime_timezone_local(), key, {"source": "local_timezone", "fallback_used": True}

    def _load_config(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return {}
        try:
            payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}


def datetime_timezone_local() -> tzinfo:
    from datetime import datetime

    return datetime.now().astimezone().tzinfo or timezone.utc
