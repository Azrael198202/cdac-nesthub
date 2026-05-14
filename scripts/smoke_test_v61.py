from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_core.events.event_bus import event_bus
from ai_core.sandbox.verified_sandbox_runtime import VerifiedSandboxRuntime
from ai_core.utils.safe_json import make_json_safe, safe_json_dumps


def test_static_verifier_requires_run_entrypoint():
    sandbox = VerifiedSandboxRuntime()
    artifact = {
        "manifest": {"implementation": {"module_path": "tool.py", "function": "run"}},
        "files": {"tool.py": "def execute(payload):\n    return {'status': 'success'}\n"},
    }
    result = sandbox.verify_tool_artifact(artifact=artifact, test_input={}, allow_network=False)
    assert result["status"] == "blocked"
    assert "entrypoint" in result["reason"].lower() or "run(payload" in result["reason"]


def test_sandbox_runner_returns_structured_missing_entrypoint_error():
    # Static verification catches the error before sandbox execution. This test
    # ensures the public result remains structured and JSON-safe.
    sandbox = VerifiedSandboxRuntime()
    artifact = {
        "manifest": {"implementation": {"module_path": "tool.py", "function": "run"}},
        "files": {"tool.py": "def validate_config(config):\n    return True\n"},
    }
    result = sandbox.verify_tool_artifact(artifact=artifact, test_input={}, allow_network=False)
    dumped = safe_json_dumps(result)
    assert "runtime_entrypoint" in dumped
    assert "run(payload" in dumped


def test_sandbox_accepts_json_safe_run_result():
    sandbox = VerifiedSandboxRuntime()
    artifact = {
        "manifest": {"implementation": {"module_path": "tool.py", "function": "run"}},
        "files": {"tool.py": "def run(payload: dict) -> dict:\n    return {'status': 'success', 'data': {'echo': payload}, 'source': 'sandbox', 'error': None}\n"},
    }
    result = sandbox.verify_tool_artifact(artifact=artifact, test_input={"x": 1}, allow_network=False)
    assert result["status"] == "passed"
    assert result["safe_to_register"] is True


def test_safe_json_handles_circular_references():
    data = {"name": "root"}
    data["self"] = data
    safe = make_json_safe(data)
    assert safe["self"]["__circular_reference__"] is True
    assert "__circular_reference__" in safe_json_dumps(data)


async def test_event_bus_safe_serialization():
    run_id = "smoke_v61"
    data = {"type": "RUN_COMPLETED"}
    data["self"] = data
    await event_bus.emit(run_id, data)
    stream = event_bus.stream(run_id)
    first = await stream.__anext__()
    assert "__circular_reference__" in first


if __name__ == "__main__":
    test_static_verifier_requires_run_entrypoint()
    test_sandbox_runner_returns_structured_missing_entrypoint_error()
    test_sandbox_accepts_json_safe_run_result()
    test_safe_json_handles_circular_references()
    asyncio.run(test_event_bus_safe_serialization())
    print("smoke_test_v61: OK")
