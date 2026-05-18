from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any
from uuid import uuid4


class RuntimeTriggerParser:
    """Parse neutral activation expressions from runtime instructions.

    The parser only recognizes structural activation forms, such as clock-like
    numeric expressions. Natural-language command phrases live in configuration
    or generated artifacts rather than source code.
    """

    CLOCK_RE = re.compile(r"(?<!\d)(\d{1,2})\s*:\s*(\d{2})\s*([AaPp][Mm])?(?!\d)")

    def parse(self, text: str, *, default_timezone: str = "Asia/Tokyo") -> dict[str, Any]:
        raw = str(text or "")
        zone = ZoneInfo(default_timezone)
        now = datetime.now(zone)
        match = self.CLOCK_RE.search(raw)
        if not match:
            return {
                "activation_id": f"activation_{uuid4().hex[:8]}",
                "mode": "manual",
                "expression": "manual",
                "timezone": default_timezone,
                "metadata": {"trigger_type": "manual", "parsed": False},
            }
        hour = int(match.group(1))
        minute = int(match.group(2))
        suffix = (match.group(3) or "").lower()
        if suffix == "pm" and hour < 12:
            hour += 12
        if suffix == "am" and hour == 12:
            hour = 0
        if hour > 23 or minute > 59:
            return {
                "activation_id": f"activation_{uuid4().hex[:8]}",
                "mode": "manual",
                "expression": "manual",
                "timezone": default_timezone,
                "metadata": {"trigger_type": "manual", "parsed": False, "reason": "invalid_clock_value"},
            }
        scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if scheduled <= now:
            scheduled += timedelta(days=1)
        expression = match.group(0).strip()
        return {
            "activation_id": f"activation_{uuid4().hex[:8]}",
            "mode": "scheduled",
            "expression": expression,
            "timezone": default_timezone,
            "metadata": {
                "trigger_type": "time",
                "expression": expression,
                "timezone": default_timezone,
                "scheduled_at": scheduled.isoformat(),
                "parsed": True,
            },
        }
