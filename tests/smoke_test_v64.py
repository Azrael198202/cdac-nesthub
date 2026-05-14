from pathlib import Path
import tempfile

from ai_core.executors.tool_call_executor import ToolCallExecutor
from ai_core.tools.sandbox_verifier import SandboxVerifier


def test_non_executable_blueprint_is_not_executable():
    executor = ToolCallExecutor()
    record = {
        "status": "blueprint_generated",
        "implementation": {
            "type": "runtime_blueprint_pending_generation",
            "function": "run",
            "module_path": "/tmp/tool.py",
        },
    }
    assert executor._has_executable_implementation(record) is False


def test_valid_runtime_tool_contract_passes_static_verifier():
    source = """
from typing import Any

def run(payload: dict[str, Any]) -> dict[str, Any]:
    return {"status": "success", "data": {"echo": payload}, "source": "test", "requires_human_confirmation": False}
"""
    artifact = {
        "manifest": {
            "implementation": {"type": "python_function", "function": "run", "module_path": "tool.py"}
        },
        "files": {"tool.py": source},
    }
    result = SandboxVerifier().verify_tool_artifact(artifact=artifact)
    assert result["status"] == "passed", result


def test_wrong_entrypoint_argument_is_blocked():
    source = """
from typing import Any

def run(input_data: dict[str, Any]) -> dict[str, Any]:
    return {"status": "success", "data": {}, "source": "test", "requires_human_confirmation": False}
"""
    artifact = {
        "manifest": {
            "implementation": {"type": "python_function", "function": "run", "module_path": "tool.py"}
        },
        "files": {"tool.py": source},
    }
    result = SandboxVerifier().verify_tool_artifact(artifact=artifact)
    assert result["status"] in {"failed", "blocked"}, result
    assert "payload" in result["reason"], result


if __name__ == "__main__":
    test_non_executable_blueprint_is_not_executable()
    test_valid_runtime_tool_contract_passes_static_verifier()
    test_wrong_entrypoint_argument_is_blocked()
    print("smoke_test_v64: OK")
