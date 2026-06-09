from auxiliary_brain.capability_acquisition.acquisition_router import RuntimeCapabilityGapImplementer
from auxiliary_brain.capability_acquisition.specification_contract_compiler import CapabilitySpecificationContractCompiler


def _manifest_with_contract():
    input_schema = {
        "type": "object",
        "properties": {
            "timezone": {"type": "string", "default": "Asia/Tokyo"},
            "format": {"type": "string", "default": "YYYY-MM-DD HH:mm", "x-role": "format"},
        },
        "required": [],
        "additionalProperties": False,
    }
    output_schema = {
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "data": {
                "type": "object",
                "properties": {
                    "current_time": {"type": "string", "x-format-source": "format"},
                    "timezone": {"type": "string"},
                },
                "required": ["current_time", "timezone"],
            },
        },
        "required": ["status", "data"],
    }
    verification_input = {"input": {"timezone": "Asia/Tokyo", "format": "YYYY-MM-DD HH:mm"}, "_runtime": {"dry_run": True}}
    spec = CapabilitySpecificationContractCompiler().compile(
        blueprint={"capability_id": "sample"},
        input_schema=input_schema,
        output_schema=output_schema,
        verification_input=verification_input,
        verification_expectations={"status": "completed"},
    )
    return {"input_schema": input_schema, "output_schema": output_schema, "specification_contract": spec}


def test_rejects_format_string_as_runtime_output_by_contract_binding():
    impl = RuntimeCapabilityGapImplementer()
    result = impl._runtime_output_contract_checks(
        verification_input={"input": {"timezone": "Asia/Tokyo", "format": "YYYY-MM-DD HH:mm"}},
        output={"status": "completed", "data": {"current_time": "YYYY-MM-DD HH:mm", "timezone": "Asia/Tokyo"}},
        expectations={"status": "completed"},
        manifest=_manifest_with_contract(),
    )
    assert result["passed"] is False
    assert result["reason"] in {"output_copied_format_or_template_instead_of_runtime_value", "output_copied_declared_format_or_template"}


def test_accepts_runtime_value_when_contract_is_satisfied_without_validator_format_repair():
    impl = RuntimeCapabilityGapImplementer()
    result = impl._runtime_output_contract_checks(
        verification_input={"input": {"timezone": "Asia/Tokyo", "format": "YYYY-MM-DD HH:mm"}},
        output={"status": "completed", "data": {"current_time": "2026-06-08 22:30", "timezone": "Asia/Tokyo"}},
        expectations={"status": "completed"},
        manifest=_manifest_with_contract(),
    )
    assert result["passed"] is True


def test_declared_default_preserves_case_and_spaces():
    impl = RuntimeCapabilityGapImplementer()
    schema = impl._extract_declared_schema_section(
        "Input parameters:\n- format: optional string, default YYYY-MM-DD HH:mm\n",
        header_patterns=[r"Input\s+parameters?"],
    )
    assert schema["properties"]["format"]["default"] == "YYYY-MM-DD HH:mm"


def test_verification_input_preserves_user_format_for_generated_code():
    from auxiliary_brain.capability_acquisition.code_generator import RuntimeBlueprintArtifactGenerator

    gen = RuntimeBlueprintArtifactGenerator()
    merged = gen._verification_input_with_schema_sample(
        {"input": {"format": "YYYY-MM-DD HH:mm"}},
        {"type": "object", "properties": {"format": {"type": "string", "default": "YYYY-MM-DD HH:mm", "x-role": "format"}}, "required": []},
        {},
        {},
    )
    assert merged["input"]["format"] == "YYYY-MM-DD HH:mm"
    assert "format_contracts" not in merged.get("_runtime", {})


def test_specification_contract_compiler_feeds_generation_and_validation_contract():
    manifest = _manifest_with_contract()
    spec = manifest["specification_contract"]
    vc = spec["verification_contract"]
    assert spec["schema_version"].endswith("/v1")
    assert any(item["path"] == "input.format" for item in vc["input_contracts"])
    assert any(item["output_path"] == "output.data.current_time" and item["source_path"] == "input.format" for item in vc["output_bindings"])
