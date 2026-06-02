from __future__ import annotations

import json
import tempfile
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auxiliary_brain.capability_acquisition import RuntimeCapabilityGapImplementer


REQUEST = """Acquire runtime capability:

Generic text transform capability.

Use runtime autonomous acquisition mode.
Constraints:
- Runtime language: Python
- Complexity level: basic
- Use Python standard library if possible
- Do not require external package installation
- Generate input schema
- Generate connection schema only if needed
- Generate secret schema only if needed
- Generate approval policy
- Verify by running a deterministic local test
- Register the capability after sandbox validation
"""
TOOL_ID = "generic_text_transform_capability"


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        template_path = Path(tmp) / "empty_templates.json"
        template_path.write_text(json.dumps({"version": "1.0", "templates": []}), encoding="utf-8")
        result = RuntimeCapabilityGapImplementer(template_path=template_path).implement_if_requested(
            user_input=REQUEST,
            evidence={"urls": []},
            run_id="verify_runtime_capability_pipeline",
            allow_implementation=True,
        )
    try:
        assert result["status"] == "registered", result
        assert result["template_source"] == "runtime_blueprint_planner", result
        assert result["validation"]["passed"] is True, result
        assert result["verification_run"]["passed"] is True, result
        assert result["registration"]["status"] == "registered", result
        stages = [(item.get("stage"), item.get("status")) for item in result.get("pipeline", [])]
        for item in [
            ("TemplateResolver", "skipped"),
            ("BlueprintPlanner", "planned"),
            ("BlueprintMaterializer", "completed"),
            ("ArtifactGenerator", "completed"),
            ("SandboxValidator", "completed"),
            ("RegistryWriter", "completed"),
        ]:
            assert item in stages, stages
        print("Runtime capability acquisition pipeline verification passed")
    finally:
        cleanup_runtime_capability_outputs(ROOT, TOOL_ID)


def cleanup_runtime_capability_outputs(root: Path, tool_id: str) -> None:
    for rel in [
        f"runtime/generated/tools/{tool_id}",
        f"runtime/generated/tests/{tool_id}",
        "runtime/generated/capability_gap_resolutions",
        "runtime/generated/self_repair/capability_acquisition",
    ]:
        shutil.rmtree(root / rel, ignore_errors=True)
    for rel in ["runtime/generated/capability_templates/runtime_planned_capability_templates.json"]:
        path = root / rel
        if path.exists():
            path.unlink()
    for rel in ["runtime/registry/tool_registry.json", "runtime/registry/module_registry.json"]:
        path = root / rel
        if not path.exists():
            continue
        try:
            registry = json.loads(path.read_text(encoding="utf-8") or "{}")
            if isinstance(registry, dict):
                registry.pop(tool_id, None)
                path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass


if __name__ == "__main__":
    main()
