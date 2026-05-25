from ai_core.execution.parameter_resolution import ParameterResolutionPipeline


def test_parameter_resolution_keeps_inputs_resources_and_policies_separate():
    pipeline = ParameterResolutionPipeline()
    context = pipeline.build_context(
        runtime_inputs={"input_a": "value", "empty": ""},
        bound_resources={"resource_ref": {"id": "r1"}},
        policy_values={"reuse_allowed": True},
        resource_reports=[{"missing_inputs": [{"field": "resource_value"}], "bound_resources": {"resource_ref_2": "r2"}}],
        agent_fields=[{"field": "input_b"}],
    )

    assert context.resolved_inputs == {"input_a": "value"}
    assert context.bound_resources["resource_ref"] == {"id": "r1"}
    assert context.bound_resources["resource_ref_2"] == "r2"
    assert context.execution_policies == {"reuse_allowed": True}
    assert [field["field"] for field in context.missing_input_fields] == ["resource_value", "input_b"]
    assert all("resource_ref" not in field["field"] for field in context.missing_input_fields)


def test_parameter_resolution_dedupes_fields_without_dropping_layer_metadata():
    pipeline = ParameterResolutionPipeline()
    context = pipeline.build_context(
        runtime_inputs={},
        resource_reports=[{"missing_inputs": [{"field": "x"}, {"field": "x"}]}],
        agent_fields=[{"field": "x"}],
    )

    fields = context.missing_input_fields
    assert len(fields) == 2
    assert {field["resolution_layer"] for field in fields} == {"resource_binding", "execution_input"}
