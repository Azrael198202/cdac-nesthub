from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[2] / "tools" / 'gmail_smtp_mail_sender'
SPEC = importlib.util.spec_from_file_location("generated_tool_under_test", ROOT / 'tool.py')
mod = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(mod)


def test_generated_tool_dry_run_contract():
    result = getattr(mod, 'run')({'dry_run': True, 'input': {'to': ['recipient@example.invalid'], 'subject': 'Capability verification', 'body': 'Dry-run verification message.', 'from_email': 'sender@example.invalid', 'dry_run': True}, 'connection': {'smtp_host': 'mock.smtp.invalid', 'smtp_port': 587, 'use_tls': False, 'starttls': True, 'timeout_seconds': 5}, 'secrets': {'username': 'dry-run-user', 'password': 'dry-run-password'}, '_runtime': {'dry_run': True}})
    assert result["status"] == "completed"
    assert result["tool_id"] == 'gmail_smtp_mail_sender'
    assert result["data"]["dry_run"] is True
    assert result["data"]["recipient_count"] == 1
