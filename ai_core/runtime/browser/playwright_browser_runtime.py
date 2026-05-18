from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BrowserEvidence:
    url: str
    status: str
    text: str = ""
    network_events: list[dict[str, Any]] = field(default_factory=list)
    screenshot_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "status": self.status,
            "text": self.text,
            "network_events": self.network_events,
            "screenshot_path": self.screenshot_path,
            "metadata": self.metadata,
        }


class PlaywrightBrowserRuntime:
    """Browser runtime contract with session reuse, wait policy, capture hooks, and evidence output."""

    def __init__(self) -> None:
        self._session: Any = None
        self._network_events: list[dict[str, Any]] = []

    @property
    def has_session(self) -> bool:
        return self._session is not None

    def attach_session(self, session: Any) -> None:
        self._session = session

    def wait_policy(self, mode: str = "network_or_dom", timeout_ms: int = 15000) -> dict[str, Any]:
        return {"mode": mode, "timeout_ms": timeout_ms, "fallback": "dom_ready"}

    def record_network_event(self, event: dict[str, Any]) -> None:
        self._network_events.append(dict(event))

    def materialize_evidence(self, url: str, text: str = "", screenshot_path: str | None = None) -> dict[str, Any]:
        return BrowserEvidence(
            url=url,
            status="success" if text or screenshot_path or self._network_events else "empty",
            text=text,
            network_events=list(self._network_events),
            screenshot_path=screenshot_path,
            metadata={"session_reused": self.has_session, "wait_policy": self.wait_policy()},
        ).to_dict()
