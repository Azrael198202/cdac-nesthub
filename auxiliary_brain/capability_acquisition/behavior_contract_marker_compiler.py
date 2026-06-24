from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any, Mapping


@dataclass(frozen=True)
class BehaviorContract:
    required_markers: list[str]
    forbidden_markers: list[str]
    required_calls: list[str]
    required_constants: list[str]
    disallow_echo_only: bool
    mock_test_required: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _flatten_text(value: Any) -> str:
    if isinstance(value, Mapping):
        return " ".join([str(k) + " " + _flatten_text(v) for k, v in value.items()]).lower()
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten_text(v) for v in value).lower()
    return str(value or "").lower()


def _quoted_constants(text: str) -> list[str]:
    constants = re.findall(r"['\"]([^'\"]{3,})['\"]", text)
    dotted_hosts = re.findall(r"\b[a-z0-9.-]+\.[a-z]{2,}\b", text)
    ports = re.findall(r"\b(?:port\s*)?(\d{2,5})\b", text)
    return sorted(set(constants + dotted_hosts + ports))


def compile_behavior_contract(specification_contract: Mapping[str, Any], behavior_class: str) -> BehaviorContract:
    text = _flatten_text(specification_contract)
    required_markers: set[str] = set()
    required_calls: set[str] = set()
    required_constants: set[str] = set(_quoted_constants(text))
    forbidden_markers: set[str] = set()

    # Generic external write/read rule. This is not business-specific: it derives markers
    # from protocols and explicit constants in the capability request.
    if behavior_class in {"external_write", "external_protocol_write", "external_read", "external_protocol_read", "local_state"}:
        forbidden_markers.update({"echo_only", "return_input_only", "pass_through_result"})

    if "smtp" in text:
        required_markers.update({"smtplib"})
        if "ssl" in text:
            required_markers.update({"SMTP_SSL"})
        required_calls.update({"login", "send_message|sendmail"})
    if "emailmessage" in text or "email.message" in text or "mail" in text or "email" in text:
        required_markers.update({"EmailMessage|email.message"})
    if "sqlite" in text or "database" in text:
        required_markers.update({"sqlite3"})
        required_calls.update({"connect"})
    if "http" in text or "api" in text or "webhook" in text:
        required_calls.update({"request|urlopen|HTTPConnection|HTTPSConnection"})
    if "file" in text or "path" in text:
        required_calls.update({"open|Path"})

    mock_test_required = behavior_class in {"external_write", "external_protocol_write", "external_read", "external_protocol_read"}
    disallow_echo_only = behavior_class not in {"pure_compute"}

    return BehaviorContract(
        required_markers=sorted(required_markers),
        forbidden_markers=sorted(forbidden_markers),
        required_calls=sorted(required_calls),
        required_constants=sorted(required_constants),
        disallow_echo_only=disallow_echo_only,
        mock_test_required=mock_test_required,
        reason=f"behavior_contract_compiled_for_{behavior_class}",
    )
