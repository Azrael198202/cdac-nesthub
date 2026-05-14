import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai_core.modules.autonomous_codegen_executor import AutonomousCodegenExecutor
from ai_core.modules.module_codegen_request import ModuleCodeGenerationRequestBuilder
from ai_core.modules.module_loader import RuntimeModuleLoader


class FakeGenerator:
    async def generate_artifact(self, *, run_id, node_id, generation_request):
        capability = generation_request.get("capability") or "sample_capability"
        return {
            "module_id": generation_request.get("module_id") or "module_sample_capability",
            "manifest": {
                "module_id": generation_request.get("module_id") or "module_sample_capability",
                "capability": capability,
                "capabilities": [capability],
                "input_schema": {"type": "object", "additionalProperties": True},
                "output_schema": {"type": "object", "additionalProperties": True},
                "runtime_interface": {"entrypoint": "module.py"},
                "safety_policy": {"requires_human_confirmation": False, "can_perform_irreversible_action": False},
                "execution_claims": {"real_execution": True, "no_mock_data": True, "uses_network": False},
            },
            "files": {
                "module.py": """
from typing import Any


def validate_config(config: dict[str, Any]) -> dict[str, Any]:
    return {\"valid\": True}


def health_check() -> dict[str, Any]:
    return {\"status\": \"ok\"}


def run(input_data: dict[str, Any]) -> dict[str, Any]:
    return {
        \"status\": \"success\",
        \"data\": {\"received\": input_data.get(\"known\", {})},
        \"source\": \"runtime_autonomous_codegen_test\",
        \"requires_human_confirmation\": False,
    }
"""
            },
            "real_execution": True,
            "no_mock_data": True,
            "uses_network": False,
        }


async def main():
    capability = "sample_capability_v59"
    builder = ModuleCodeGenerationRequestBuilder()
    req = builder.create_request(
        module_id="module_sample_capability_v59",
        capability=capability,
        blueprint={
            "module_id": "module_sample_capability_v59",
            "capability": capability,
            "source_step": {
                "step_id": "step_1",
                "parameters": {"known": {"subject": "demo"}, "missing_required": [], "optional": {}},
            },
        },
        user_input="sample request",
    )
    executor = AutonomousCodegenExecutor()
    executor.artifact_generator = FakeGenerator()
    result = await executor.execute_request_file(
        request_path=req["request_path"],
        run_id="smoke_v59",
        node_id="execution",
        step_id="step_1",
        test_input={"known": {"subject": "demo"}, "parameters": {"known": {"subject": "demo"}}},
    )
    assert result.get("enabled") is True, result
    module = RuntimeModuleLoader().load_by_capability(capability)
    assert module is not None, result
    out = module.run({"known": {"subject": "demo"}})
    assert out.get("status") == "success", out
    print("smoke_test_v59: OK")


if __name__ == "__main__":
    asyncio.run(main())
