from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auxiliary_brain.capability_acquisition.acquisition_router import RuntimeCapabilityGapImplementer
from auxiliary_brain.capability_acquisition.code_generator import RuntimeBlueprintArtifactGenerator


TOOL_ID = "current_time_provider"

REQUEST = """Acquire runtime capability:

Current time provider.

Use runtime autonomous acquisition mode.

Capability identity requirements:
- Create a NEW runtime capability.
- Capability id must be: current_time_provider
- This capability must be generic

Constraints:
- Runtime language: Python
- Complexity level basic
- Use Python standard library only
- Prefer datetime and zoneinfo
- Do not require external package installation
- Do not call external network APIs
- Do not return a hardcoded time
- Generate input schema
- Generate output schema
- Generate connection schema only if needed
- Generate secret schema only if needed
- Generate approval policy
- Verify by running a deterministic local sandbox test
- Register the capability only after sandbox validation
"""


class FakeBrainClient:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def complete_sync(self, **kwargs):
        self.calls.append(kwargs)
        contract = json.loads(kwargs["messages"][1]["content"].split("\n", 1)[1])
        module = contract["entrypoint"]["module"]
        function = contract["entrypoint"]["function"]
        tool_id = contract["tool_id"]
        source = f'''from __future__ import annotations
from datetime import datetime
from typing import Any

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

TOOL_ID = {tool_id!r}

def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().casefold() in {{"1", "true", "yes", "y", "on"}}

def {function}(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {{}}
    data = payload.get("input") if isinstance(payload.get("input"), dict) else payload
    timezone_name = str(data.get("timezone") or "UTC")
    fixed = data.get("verification_fixed_epoch")
    if fixed is not None:
        moment = datetime.fromtimestamp(float(fixed), tz=ZoneInfo("UTC") if ZoneInfo else None)
    else:
        tz = ZoneInfo(timezone_name) if ZoneInfo else None
        moment = datetime.now(tz)
    if ZoneInfo and timezone_name != "UTC":
        moment = moment.astimezone(ZoneInfo(timezone_name))
    return {{
        "status": "completed",
        "tool_id": TOOL_ID,
        "data": {{
            "timezone": timezone_name,
            "iso": moment.isoformat(),
            "epoch_seconds": moment.timestamp(),
            "source": "python_standard_library",
            "dry_run": _bool(data.get("dry_run"), False),
        }},
        "message": "Runtime value produced without external network calls.",
    }}
'''
        test = f'''import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "tools" / {tool_id!r}
SPEC = importlib.util.spec_from_file_location("generated_tool_under_test", ROOT / {module!r})
mod = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(mod)

def test_runtime_value_is_generated_from_standard_library():
    out = mod.{function}({{"input": {{"timezone": "UTC", "verification_fixed_epoch": 0, "dry_run": True}}}})
    assert out["status"] == "completed"
    assert out["tool_id"] == {tool_id!r}
    assert out["data"]["timezone"] == "UTC"
    assert out["data"]["iso"].startswith("1970-01-01")
'''
        artifact = {
            "files": [{"path": module, "content": source}, {"path": "test_tool.py", "content": test}],
            "input_schema": {
                "type": "object",
                "required": ["timezone"],
                "properties": {
                    "timezone": {"type": "string", "default": "UTC"},
                    "dry_run": {"type": "boolean", "default": False},
                    "verification_fixed_epoch": {"type": "number"},
                },
                "additionalProperties": False,
            },
            "output_schema": {
                "type": "object",
                "required": ["status", "data"],
                "properties": {
                    "status": {"type": "string"},
                    "tool_id": {"type": "string"},
                    "data": {"type": "object"},
                    "message": {"type": "string"},
                },
                "additionalProperties": False,
            },
            "connection_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False, "x-empty-schema-allowed": True},
            "secret_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False, "x-empty-schema-allowed": True},
            "verification_input": {"input": {"timezone": "UTC", "verification_fixed_epoch": 0, "dry_run": True}, "connection": {}, "secrets": {}},
            "verification_expectations": {"status": "completed"},
        }
        return SimpleNamespace(status="completed", content=json.dumps(artifact), route={"brain": kwargs["brain"], "task_type": kwargs["task_type"], "complexity": kwargs["complexity"]}, error="")


def cleanup() -> None:
    for path in [ROOT / f"runtime/generated/tools/{TOOL_ID}", ROOT / f"runtime/generated/tests/{TOOL_ID}"]:
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
    for rel in ["runtime/registry/tool_registry.json", "runtime/registry/module_registry.json"]:
        path = ROOT / rel
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8") or "{}")
        except Exception:
            data = {}
        if isinstance(data, dict):
            data.pop(TOOL_ID, None)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    cleanup()
    client = FakeBrainClient()
    impl = RuntimeCapabilityGapImplementer()
    impl.blueprint_artifact_generator = RuntimeBlueprintArtifactGenerator(llm_client=client)
    result = impl.implement_if_requested(user_input=REQUEST, evidence={}, run_id="verify_v22_5_policy_backed_local_codegen_registration", allow_implementation=True)
    assert result.get("status") == "registered", json.dumps(result, ensure_ascii=False, indent=2)[:5000]
    pipeline = [(item.get("stage"), item.get("status")) for item in result.get("pipeline", [])]
    assert ("CapabilityAcquisitionClass", "runtime_native") in pipeline, pipeline
    assert ("WebEvidenceRetriever", "not_required") in pipeline, pipeline
    assert ("SandboxValidator", "completed") in pipeline, pipeline
    assert ("VerificationRun", "completed") in pipeline, pipeline
    assert ("RegistryWriter", "completed") in pipeline, pipeline
    assert client.calls, "LiteLLM code-generation path was not used"
    assert client.calls[0]["task_type"] == "runtime_tool_code_generation"
    assert client.calls[0]["complexity"] in {"basic", "default"}, client.calls[0]
    record = (result.get("registration") or {}).get("tool_record") or {}
    assert record.get("status") == "enabled", record
    print("verify_v22_5_policy_backed_local_codegen_registration: ok")


if __name__ == "__main__":
    main()
