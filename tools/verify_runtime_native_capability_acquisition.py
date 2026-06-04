from __future__ import annotations

from pathlib import Path
import json
import shutil
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from auxiliary_brain.capability_acquisition.acquisition_router import RuntimeCapabilityGapImplementer


REQUEST = """Acquire runtime capability:

Scheduled Trigger.

Use runtime autonomous acquisition mode.

Capability identity requirements:
- Create a NEW runtime capability.
- Capability id must be: scheduled_trigger
- Capability name must be: Scheduled Trigger
- This capability must be generic

Constraints:
- Runtime language: Python
- Complexity level: basic
- Use Python standard library if possible
- Do not require external package installation
- Persist timers in local runtime storage
- Support multiple named timers
- Each timer must have:
  - timer name
  - enabled / disabled status
  - schedule definition
  - target type
  - target agent id or name
  - runtime parameters passed to the target agent
- Support creating timer
- Support listing timers
- Support enabling timer by name
- Support disabling timer by name
- Support deleting timer by name
- Support updating timer parameters
- Generate input schema
- Generate connection schema
- Generate secret schema
- Generate approval policy
- Verify by creating a dry-run timer and checking persistence
- Verify enable / disable / delete behavior in sandbox
- Register the capability only after sandbox validation

The capability acquisition is complete only after:
1. implementation generated
2. input / connection / secret schemas generated
3. sandbox test passed
4. registry updated
5. verification run completed
6. status is registered
"""


def main() -> None:
    for path in [Path("runtime/generated/tools/scheduled_trigger"), Path("runtime/generated/tests/scheduled_trigger")]:
        if path.exists():
            shutil.rmtree(path)
    result = RuntimeCapabilityGapImplementer().implement_if_requested(
        user_input=REQUEST,
        evidence={},
        run_id="verify_runtime_native_capability_acquisition",
        allow_implementation=True,
    )
    assert result.get("status") == "registered", json.dumps(result, ensure_ascii=False, indent=2)[:4000]
    pipeline = [(item.get("stage"), item.get("status")) for item in result.get("pipeline", [])]
    assert ("CapabilityAcquisitionClass", "runtime_native") in pipeline, pipeline
    assert ("WebEvidenceRetriever", "not_required") in pipeline, pipeline
    validation = result.get("validation") or {}
    verification = result.get("verification_run") or {}
    assert validation.get("passed") is True, validation
    assert verification.get("passed") is True, verification
    registration = result.get("registration") or {}
    tool_record = registration.get("tool_record") or {}
    assert tool_record.get("status") == "enabled", tool_record
    assert tool_record.get("connection_schema", {}).get("x-empty-schema-allowed") is True
    assert tool_record.get("secret_schema", {}).get("x-empty-schema-allowed") is True
    print("runtime native capability acquisition verification passed")


if __name__ == "__main__":
    main()
