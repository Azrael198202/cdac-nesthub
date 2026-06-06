from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Any

TOOL_ID = 'gmail_smtp_mail_sender'


class _DryRunSMTP:
    def __init__(self, host: str, port: int, timeout: float | None = None) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.messages: list[EmailMessage] = []
        self.started_tls = False
        self.logged_in = False

    def __enter__(self) -> "_DryRunSMTP":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.quit()

    def starttls(self) -> None:
        self.started_tls = True

    def login(self, username: str, password: str) -> None:
        self.logged_in = bool(username or password)

    def send_message(self, message: EmailMessage) -> dict[str, Any]:
        self.messages.append(message)
        return {}

    def quit(self) -> None:
        return None


def _as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().casefold()
    if text in {"true", "1", "yes", "y", "on"}:
        return True
    if text in {"false", "0", "no", "n", "off"}:
        return False
    return default


def _as_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _first_present(*values: Any, default: Any = None) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return default


def _build_message(runtime_input: dict[str, Any], connection: dict[str, Any]) -> EmailMessage:
    to_values = _as_list(runtime_input.get("to"))
    subject = str(runtime_input.get("subject") or "").strip()
    body = str(runtime_input.get("body") or "")
    from_email = str(_first_present(runtime_input.get("from_email"), connection.get("default_from_email"), default="")).strip()
    if not to_values:
        raise ValueError("input.to is required")
    if not subject:
        raise ValueError("input.subject is required")
    if not body:
        raise ValueError("input.body is required")
    if not from_email:
        raise ValueError("input.from_email or connection.default_from_email is required")
    message = EmailMessage()
    message["From"] = from_email
    message["To"] = ", ".join(to_values)
    cc_values = _as_list(runtime_input.get("cc"))
    if cc_values:
        message["Cc"] = ", ".join(cc_values)
    reply_to = str(runtime_input.get("reply_to") or "").strip()
    if reply_to:
        message["Reply-To"] = reply_to
    message["Subject"] = subject
    subtype = str(runtime_input.get("body_subtype") or "plain").strip().lower()
    if subtype not in {"plain", "html"}:
        subtype = "plain"
    message.set_content(body, subtype=subtype)
    return message


def run(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = _as_mapping(payload)
    runtime = _as_mapping(payload.get("_runtime"))
    runtime_input = _as_mapping(payload.get("input") or payload.get("runtime_input") or payload.get("parameters") or payload)
    connection = _as_mapping(payload.get("connection") or payload.get("profile") or payload.get("runtime_connection") or runtime.get("connection"))
    secrets = _as_mapping(payload.get("secrets") or payload.get("secret") or payload.get("runtime_secrets") or runtime.get("secrets"))
    dry_run = _as_bool(_first_present(runtime_input.get("dry_run"), payload.get("dry_run"), runtime.get("dry_run"), default=False), default=False)
    host = str(connection.get("smtp_host") or "").strip()
    port = int(connection.get("smtp_port") or 0)
    timeout = float(connection.get("timeout_seconds") or 20)
    if not host:
        raise ValueError("connection.smtp_host is required")
    if port <= 0 or port > 65535:
        raise ValueError("connection.smtp_port must be between 1 and 65535")
    message = _build_message(runtime_input, connection)
    recipients = _as_list(runtime_input.get("to")) + _as_list(runtime_input.get("cc")) + _as_list(runtime_input.get("bcc"))
    username = str(secrets.get("username") or "")
    password = str(secrets.get("password") or "")
    use_tls = _as_bool(connection.get("use_tls"), default=True)
    starttls = _as_bool(connection.get("starttls"), default=False)
    smtp_class = _DryRunSMTP if dry_run else (smtplib.SMTP_SSL if use_tls and not starttls else smtplib.SMTP)
    with smtp_class(host, port, timeout=timeout) as smtp:
        if starttls and hasattr(smtp, "starttls"):
            smtp.starttls()
        if username or password:
            smtp.login(username, password)
        refused = smtp.send_message(message)
    return {"status": "completed", "tool_id": TOOL_ID, "data": {"dry_run": dry_run, "host": host, "port": port, "recipient_count": len(recipients), "subject": str(message["Subject"]), "refused_recipients": refused or {}, "sent": not dry_run}, "message": "Message flow completed.", "provenance": {"source": "runtime_generated_tool", "side_effects": not dry_run}}
