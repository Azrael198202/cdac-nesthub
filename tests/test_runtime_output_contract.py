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
