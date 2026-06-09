from auxiliary_brain.capability_acquisition.acquisition_router import RuntimeCapabilityGapImplementer


def _manifest():
    return {
        "output_schema": {
            "type": "object",
            "properties": {
                "current_time": {"type": "string"},
                "timezone": {"type": "string"},
            },
            "required": ["current_time", "timezone"],
        }
    }


def test_rejects_format_string_as_runtime_output():
    impl = RuntimeCapabilityGapImplementer()
    result = impl._runtime_output_contract_checks(
        verification_input={"timezone": "Asia/Tokyo", "format": "YYYY-MM-DD HH:mm"},
        output={"status": "completed", "current_time": "yyyy-mm-dd", "timezone": "Asia/Tokyo"},
        expectations={"status": "completed"},
        manifest=_manifest(),
    )
    assert result["passed"] is False
    assert result["reason"] in {"unresolved_placeholder_output", "output_copied_format_or_template_instead_of_runtime_value"}


def test_accepts_value_matching_declared_temporal_format():
    impl = RuntimeCapabilityGapImplementer()
    result = impl._runtime_output_contract_checks(
        verification_input={"timezone": "Asia/Tokyo", "format": "YYYY-MM-DD HH:mm"},
        output={"status": "completed", "current_time": "2026-06-08 22:30", "timezone": "Asia/Tokyo"},
        expectations={"status": "completed"},
        manifest=_manifest(),
    )
    assert result["passed"] is True


def test_user_facing_datetime_format_is_converted_for_contract_checks():
    impl = RuntimeCapabilityGapImplementer()
    assert impl._to_python_datetime_format("YYYY-MM-DD HH:mm") == "%Y-%m-%d %H:%M"
    assert impl._to_python_datetime_format("yyyy-mm-dd") == "%Y-%m-%d"


def test_declared_default_preserves_case_and_spaces():
    impl = RuntimeCapabilityGapImplementer()
    schema = impl._extract_declared_schema_section(
        "Input parameters:\n- format: optional string, default YYYY-MM-DD HH:mm\n",
        header_patterns=[r"Input\s+parameters?"],
    )
    assert schema["properties"]["format"]["default"] == "YYYY-MM-DD HH:mm"


def test_generator_normalizes_datetime_verification_sample_without_domain_logic():
    from auxiliary_brain.capability_acquisition.code_generator import RuntimeBlueprintArtifactGenerator

    gen = RuntimeBlueprintArtifactGenerator()
    merged = gen._verification_input_with_schema_sample(
        {"input": {"format": "YYYY-MM-DD HH:mm"}},
        {"type": "object", "properties": {"format": {"type": "string", "default": "YYYY-MM-DD HH:mm"}}, "required": []},
        {},
        {},
    )
    assert merged["input"]["format"] == "%Y-%m-%d %H:%M"
