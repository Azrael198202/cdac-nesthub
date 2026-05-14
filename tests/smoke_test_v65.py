from jsonschema import ValidationError, validate

from ai_core.runtime.runtime_template_generator import RuntimeTemplateGenerator


def test_input_parsing_schema_is_stage_minimal():
    gen = RuntimeTemplateGenerator()
    schema = gen._default_schema("input_parsing")
    assert "tasks" not in schema.get("properties", {})
    assert "required_capabilities" not in schema.get("properties", {})
    assert schema.get("not") == {"required": ["tasks"]}

    valid = {
        "language": "en",
        "original_input": "Example request",
        "parsed_entities": {"entity": "value"},
        "semantic_modifiers": ["detailed"],
        "constraints": {},
        "temporal_expressions": [],
        "missing_information": [],
        "safety_notes": [],
    }
    validate(instance=valid, schema=schema)

    invalid = dict(valid)
    invalid["tasks"] = ["should_not_be_here"]
    try:
        validate(instance=invalid, schema=schema)
        raise AssertionError("input_parsing schema allowed top-level tasks")
    except ValidationError:
        pass


def test_intent_recognition_schema_is_stage_minimal():
    gen = RuntimeTemplateGenerator()
    schema = gen._default_schema("intent_recognition")
    assert "tasks" not in schema.get("properties", {})
    assert "required_capabilities" not in schema.get("properties", {})
    assert schema.get("not") == {"required": ["tasks"]}

    valid = {
        "intent_type": "generic_information_request",
        "intent_summary": "The user asks for current information.",
        "normalized_intent": {"read_only": True},
        "confidence": {"overall": 0.9, "intent": 0.9, "parameter_understanding": 0.9},
        "human_review": {"required": False},
    }
    validate(instance=valid, schema=schema)

    invalid = dict(valid)
    invalid["tasks"] = [{"task_id": "bad"}]
    try:
        validate(instance=invalid, schema=schema)
        raise AssertionError("intent_recognition schema allowed top-level tasks")
    except ValidationError:
        pass


def test_workflow_planning_owns_executable_steps():
    gen = RuntimeTemplateGenerator()
    schema = gen._default_schema("workflow_planning")
    step = {
        "step_id": "step_1",
        "step_type": "generic_capability_request",
        "objective": "Execute a read-only runtime capability based on upstream semantics.",
        "input_from": ["input_parsing", "intent_recognition"],
        "required_capability": "generic_external_information_lookup",
        "parameters": {"known": {}, "optional": {}, "missing_required": []},
        "execution_ready": True,
        "human_interaction": {"required": False, "type": "none", "fields": {}},
        "next_action": "capability_resolution_or_execute",
        "depends_on": [],
        "requires_human_confirmation": False,
    }
    validate(instance={"planned_steps": [step], "blocking_missing_information": [], "required_capabilities": []}, schema=schema)


if __name__ == "__main__":
    test_input_parsing_schema_is_stage_minimal()
    test_intent_recognition_schema_is_stage_minimal()
    test_workflow_planning_owns_executable_steps()
    print("smoke_test_v65: OK")
