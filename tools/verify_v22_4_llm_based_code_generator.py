from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from auxiliary_brain.capability_acquisition.code_generator import RuntimeBlueprintArtifactGenerator


class FakeBrainClient:
    def __init__(self) -> None:
        self.calls = []

    def complete_sync(self, **kwargs):
        self.calls.append(kwargs)
        contract = json.loads(kwargs["messages"][1]["content"].split("\n", 1)[1])
        tool_id = contract["tool_id"]
        function = contract["entrypoint"]["function"]
        module = contract["entrypoint"]["module"]
        artifact = {
            "files": [
                {
                    "path": module,
                    "content": f"from typing import Any\nTOOL_ID={tool_id!r}\ndef {function}(payload: dict[str, Any] | None=None) -> dict[str, Any]:\n    return {{'status':'completed','tool_id':TOOL_ID,'data':{{'echo': payload or {{}}}}}}\n",
                },
                {"path": "test_tool.py", "content": "def test_placeholder():\n    assert True\n"},
            ],
            "input_schema": contract["input_schema"],
            "output_schema": contract["output_schema"],
            "connection_schema": contract["connection_schema"],
            "secret_schema": contract["secret_schema"],
            "verification_input": contract["verification_input"],
            "verification_expectations": {"status": "completed"},
        }
        return SimpleNamespace(status="completed", content=json.dumps(artifact), route={"brain": "auxiliary_brain", "task_type": "runtime_tool_code_generation"}, error="")


def test_codegen_uses_litellm_path_and_not_builtin_templates() -> None:
    client = FakeBrainClient()
    generator = RuntimeBlueprintArtifactGenerator(llm_client=client)
    artifact = generator.materialize(
        {
            "capability_id": "example_runtime_provider",
            "description": "Return a value derived from runtime input.",
            "input_schema": {"type": "object", "properties": {"value": {"type": "string", "default": "x"}}, "required": [], "additionalProperties": True},
            "output_schema": {"type": "object", "required": ["status", "data"], "properties": {"status": {"type": "string"}, "data": {"type": "object"}}, "additionalProperties": False},
            "acquisition_policy": {"allow_llm_code_generation": True},
        },
        identity_contract={"requested_capability_id": "example_runtime_provider"},
    )
    assert client.calls, "LLM code generation route was not called"
    assert client.calls[0]["brain"] == "auxiliary_brain"
    assert client.calls[0]["task_type"] == "runtime_tool_code_generation"
    assert artifact["artifact_kind"] == "real_runtime_implementation"
    assert artifact["code_generation"]["mode"] == "llm_or_supplied_files_only"
    assert artifact["input_schema"]["properties"]["value"]["default"] == "x"


def test_codegen_source_has_no_capability_specific_keyword_branches() -> None:
    source = Path("auxiliary_brain/capability_acquisition/code_generator.py").read_text(encoding="utf-8").casefold()
    forbidden = ["basic_smtp", "_smtp_", "runtime_moment", "zoneinfo", "timestamp_iso", "current time"]
    found = [item for item in forbidden if item in source]
    assert not found, found


if __name__ == "__main__":
    test_codegen_uses_litellm_path_and_not_builtin_templates()
    test_codegen_source_has_no_capability_specific_keyword_branches()
    print("verify_v22_4_llm_based_code_generator: ok")
