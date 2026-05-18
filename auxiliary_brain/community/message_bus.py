from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass(slots=True)
class RuntimeMessage:
    message_id: str
    sender_id: str
    receiver_id: str
    channel: str
    payload: dict[str, Any]
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "sender_id": self.sender_id,
            "receiver_id": self.receiver_id,
            "channel": self.channel,
            "payload": dict(self.payload),
            "created_at": self.created_at,
        }


class RuntimeMessageBus:
    """In-process neutral message exchange for generated agents."""

    def __init__(self) -> None:
        self._messages: list[RuntimeMessage] = []
        self._by_receiver: dict[str, list[RuntimeMessage]] = defaultdict(list)

    def publish(
        self,
        *,
        sender_id: str,
        receiver_id: str,
        channel: str,
        payload: dict[str, Any],
    ) -> RuntimeMessage:
        message = RuntimeMessage(
            message_id=f"msg_{uuid4().hex[:12]}",
            sender_id=sender_id,
            receiver_id=receiver_id,
            channel=channel,
            payload=payload,
        )
        self._messages.append(message)
        self._by_receiver[receiver_id].append(message)
        return message

    def collect(self, receiver_id: str) -> list[dict[str, Any]]:
        return [message.to_dict() for message in self._by_receiver.get(receiver_id, [])]

    def dump(self) -> list[dict[str, Any]]:
        return [message.to_dict() for message in self._messages]
