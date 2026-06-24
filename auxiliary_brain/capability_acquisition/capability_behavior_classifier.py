from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Mapping


@dataclass(frozen=True)
class CapabilityBehaviorClass:
    behavior_class: str
    side_effects: str
    requires_real_implementation: bool
    allow_echo_implementation: bool
    requires_behavior_contract: bool
    evidence: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_EXTERNAL_WRITE_TERMS = (
    "send", "upload", "post", "publish", "create", "update", "delete", "write",
    "notify", "message", "mail", "email", "sms", "payment", "ticket", "calendar",
)
_EXTERNAL_READ_TERMS = (
    "search", "fetch", "download", "read", "retrieve", "query", "api", "web", "http",
)
_LOCAL_STATE_TERMS = (
    "sqlite", "database", "db", "file", "store", "save", "memory", "cache",
)
_RUNTIME_NATIVE_TERMS = (
    "datetime", "time", "math", "json", "uuid", "hash", "standard library", "local runtime",
)
_PROTOCOL_TERMS = (
    "smtp", "imap", "pop3", "http", "oauth", "ssl", "tls", "webhook", "socket",
)


def _text_from_contract(contract: Mapping[str, Any] | str | None) -> str:
    if contract is None:
        return ""
    if isinstance(contract, str):
        return contract.lower()
    parts: list[str] = []
    def walk(value: Any) -> None:
        if isinstance(value, Mapping):
            for k, v in value.items():
                parts.append(str(k))
                walk(v)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                walk(item)
        else:
            parts.append(str(value))
    walk(contract)
    return " ".join(parts).lower()


def classify_capability_behavior(contract: Mapping[str, Any] | str | None) -> CapabilityBehaviorClass:
    text = _text_from_contract(contract)
    evidence: list[str] = []

    def has_any(terms: tuple[str, ...]) -> bool:
        found = [t for t in terms if t in text]
        evidence.extend(found)
        return bool(found)

    protocol = has_any(_PROTOCOL_TERMS)
    external_write = has_any(_EXTERNAL_WRITE_TERMS)
    external_read = has_any(_EXTERNAL_READ_TERMS)
    local_state = has_any(_LOCAL_STATE_TERMS)
    runtime_native = has_any(_RUNTIME_NATIVE_TERMS)

    if protocol and external_write:
        return CapabilityBehaviorClass("external_protocol_write", "external_write", True, False, True, sorted(set(evidence)))
    if external_write:
        return CapabilityBehaviorClass("external_write", "external_write", True, False, True, sorted(set(evidence)))
    if protocol and external_read:
        return CapabilityBehaviorClass("external_protocol_read", "external_read", True, False, True, sorted(set(evidence)))
    if external_read:
        return CapabilityBehaviorClass("external_read", "external_read", True, False, True, sorted(set(evidence)))
    if local_state:
        return CapabilityBehaviorClass("local_state", "local_state", True, False, True, sorted(set(evidence)))
    if runtime_native:
        return CapabilityBehaviorClass("pure_compute", "none", False, True, False, sorted(set(evidence)))
    return CapabilityBehaviorClass("unknown", "unknown", True, False, True, sorted(set(evidence)))
