from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from auxiliary_brain.capability_acquisition.code_generator import RuntimeBlueprintArtifactGenerator


@dataclass
class FakeResult:
    status: str
    content: str = ""
    route: dict | None = None
    error: str = ""


class FakeLLM:
    def __init__(self):
        self.calls = []

    def complete_sync(self, **kwargs):
        self.calls.append(kwargs)
        # First attempt returns a non-JSON-serializable runtime object.
        if len(self.calls) == 1:
            artifact = {
                "files": [
                    {"path": "tool.py", "content": "from datetime import datetime\ndef run(payload):\n    return {'value': datetime.utcnow()}\n"},
                    {"path": "test_tool.py", "content": "import tool\nassert tool.run({})\n"},
                ],
                "input_schema": {"type": "object", "properties": {}},
                "output_schema": {"type": "object", "properties": {}},
            }
        else:
            artifact = {
                "files": [
                    {"path": "tool.py", "content": "from datetime import datetime, timezone\ndef run(payload):\n    return {'value': datetime.now(timezone.utc).isoformat()}\n"},
                    {"path": "test_tool.py", "content": "import json, tool\njson.dumps(tool.run({}))\n"},
                ],
                "input_schema": {"type": "object", "properties": {}},
                "output_schema": {"type": "object", "properties": {"value": {"type": "string"}}},
            }
        return FakeResult(status="completed", content=json.dumps(artifact), route={"complexity": kwargs.get("complexity")})


def main():
    llm = FakeLLM()
    gen = RuntimeBlueprintArtifactGenerator(llm_client=llm)  # type: ignore[arg-type]
    blueprint = {
        "capability_id": "unit_runtime_capability",
        "description": "Complexity level: basic. Use Python standard library only.",
        "input_schema": {"type": "object", "properties": {}},
        "output_schema": {"type": "object", "properties": {}},
        "verification_input": {"input": {}, "connection": {}, "secrets": {}, "_runtime": {"dry_run": True}},
    }
    artifact = gen.materialize(blueprint)
    assert artifact["artifact_kind"] == "real_runtime_implementation", artifact.get("code_generation")
    assert len(llm.calls) == 2, len(llm.calls)
    assert all(call.get("complexity") == "basic" for call in llm.calls), [call.get("complexity") for call in llm.calls]
    codegen = artifact.get("code_generation") or {}
    assert codegen.get("attempts"), codegen
    assert codegen["attempts"][0]["status"] == "preflight_failed", codegen["attempts"][0]
    assert codegen.get("preflight", {}).get("passed") is True, codegen.get("preflight")
    print("v23.11 preflight repair stability verification passed")


if __name__ == "__main__":
    main()
