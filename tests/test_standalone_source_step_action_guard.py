from ai_core.executors.llm_json_executor import LLMJsonExecutor


def test_standalone_source_step_replaces_human_interaction_when_external_material_required():
    ex = LLMJsonExecutor()
    state = {
        "runtime_options": {"standalone_dataflow_source_step": True},
        "results": {
            "knowledge_evaluation": {
                "requires_external_information": True,
                "needs_web_search": True,
                "evidence_required": True,
            }
        },
    }
    action = ex._repair_source_step_action(
        state=state,
        selected_action="ask_user",
        containers=[{"missing_information": []}],
        step={},
    )
    assert action == "web_query"


def test_standalone_source_step_keeps_human_interaction_when_missing_information_exists():
    ex = LLMJsonExecutor()
    state = {
        "runtime_options": {"standalone_dataflow_source_step": True},
        "results": {"knowledge_evaluation": {"needs_web_search": True}},
    }
    action = ex._repair_source_step_action(
        state=state,
        selected_action="ask_user",
        containers=[{"missing_information": ["required value"]}],
        step={},
    )
    assert action == "ask_user"


def test_non_standalone_step_preserves_selected_action():
    ex = LLMJsonExecutor()
    action = ex._repair_source_step_action(
        state={"runtime_options": {}},
        selected_action="ask_user",
        containers=[{"requires_external_information": True}],
        step={},
    )
    assert action == "ask_user"
