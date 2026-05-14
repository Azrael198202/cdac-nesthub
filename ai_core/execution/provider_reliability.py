from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from ai_core.config.paths import RUNTIME_KNOWLEDGE
from ai_core.utils.safe_json import safe_json_dumps


class ProviderReliabilityTracker:
    """Record lightweight provider reliability observations.

    The tracker works on hostnames only and does not contain any domain logic.
    """

    def __init__(self) -> None:
        self.path = RUNTIME_KNOWLEDGE / "provider_reliability.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record_attempt(self, *, candidate: dict[str, Any], status: str, classification: dict[str, Any] | None = None) -> None:
        url = str(candidate.get("url") or candidate.get("official_documentation_url") or "") if isinstance(candidate, dict) else ""
        host = urlparse(url).netloc if url else ""
        payload = {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "host": host,
            "url": url,
            "status": status,
            "classification": classification or {},
            "tool_type": candidate.get("tool_type") if isinstance(candidate, dict) else None,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(safe_json_dumps(payload) + "\n")
