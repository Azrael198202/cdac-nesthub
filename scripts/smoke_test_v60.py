from __future__ import annotations

from ai_core.research.endpoint_verifier import EndpointVerifier
from ai_core.sandbox.verified_sandbox_runtime import VerifiedSandboxRuntime


def test_endpoint_verifier_detects_html_without_network_monkeypatch():
    verifier = EndpointVerifier()
    body = b"<html><head><title>x</title></head><body>data</body></html>"
    assert verifier._looks_like_html(body) is True
    assert verifier._is_json_response("text/html", body) is False


def test_endpoint_verifier_detects_json_sample():
    verifier = EndpointVerifier()
    assert verifier._is_json_response("application/json", b'{"ok": true}') is True
    assert verifier._is_json_response("text/plain", b'[1, 2, 3]') is True


def test_static_failure_reason_contains_findings():
    sandbox = VerifiedSandboxRuntime()
    artifact = {
        "manifest": {"implementation": {"module_path": "tool.py", "function": "run"}},
        "files": {"tool.py": "import os\ndef run(input_data):\n    return {'status': 'success'}\n"},
    }
    result = sandbox.verify_tool_artifact(artifact=artifact, test_input={}, allow_network=False)
    assert result["status"] == "blocked"
    assert "blocked import" in result["reason"]


if __name__ == "__main__":
    test_endpoint_verifier_detects_html_without_network_monkeypatch()
    test_endpoint_verifier_detects_json_sample()
    test_static_failure_reason_contains_findings()
    print("smoke_test_v60: OK")
