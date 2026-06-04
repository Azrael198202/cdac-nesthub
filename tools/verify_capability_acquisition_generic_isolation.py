from __future__ import annotations

import json
import tempfile
from pathlib import Path

from auxiliary_brain.capability_acquisition.acquisition_router import RuntimeCapabilityGapImplementer
from auxiliary_brain.capability_acquisition.code_generator import RuntimeBlueprintArtifactGenerator


def assert_true(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def verify_new_capability_artifact_directory_is_cleaned() -> None:
    impl = RuntimeCapabilityGapImplementer()
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        impl.generated_dir = base / "tools"
        impl.generated_tests_dir = base / "tests"
        stale_dir = impl.generated_dir / "new_capability"
        stale_dir.mkdir(parents=True)
        (stale_dir / "manifest.json").write_text(json.dumps({"input_schema": {"properties": {"stale": {"type": "string"}}}}), encoding="utf-8")
        template = {
            "template_id": "new_capability",
            "files": [{"path": "tool.py", "content": "def run(payload):\n    return {'status':'completed','data':{}}\n"}],
            "input_schema": {"type": "object", "properties": {"fresh": {"type": "string"}}, "required": ["fresh"], "additionalProperties": False},
            "output_schema": {"type": "object", "properties": {"status": {"type": "string"}, "data": {"type": "object"}}, "required": ["status", "data"], "additionalProperties": False},
            "connection_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False, "x-empty-schema-allowed": True},
            "secret_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False, "x-empty-schema-allowed": True},
            "artifact_kind": "real_runtime_implementation",
        }
        artifact = impl._write_artifact(template=template, evidence={}, run_id="r1", dependency_resolution={})
        manifest = json.loads(Path(artifact["manifest_path"]).read_text(encoding="utf-8"))
        assert_true("fresh" in manifest["input_schema"]["properties"], "fresh schema was not written")
        assert_true("stale" not in json.dumps(manifest), "stale schema leaked into new acquisition")


def verify_generator_has_no_static_route_for_example_capability() -> None:
    gen = RuntimeBlueprintArtifactGenerator()
    artifact = gen.materialize({"capability_id": "arbitrary_new_capability", "description": "arbitrary capability"}, identity_contract={"requested_capability_id": "arbitrary_new_capability"})
    assert_true(artifact["template_id"] == "arbitrary_new_capability", "tool id mismatch")
    assert_true(artifact["artifact_kind"] == "blueprint_only_not_registerable", "unknown capability must not be materialized by a static route")


def main() -> None:
    verify_new_capability_artifact_directory_is_cleaned()
    verify_generator_has_no_static_route_for_example_capability()
    print("capability_acquisition_generic_isolation: ok")


if __name__ == "__main__":
    main()
