from ai_core.roles import RoleProfileSelector, RoleScopedContextReducer


def test_information_retrieval_role_selected_and_context_reduced():
    state = {
        "run_id": "test",
        "input": "Please retrieve the latest result.",
        "results": {
            "intent_recognition": {
                "intent_type": "generic_lookup",
                "required_capabilities": ["external_information_lookup"],
            },
            "execution": {
                "api_discovery": {"large": "x" * 10000},
                "documentation_evidence": [
                    {
                        "document": {
                            "url": "https://example.test/data",
                            "title": "Example Data",
                            "text_excerpt": "Example Data for location ABC on 2026-05-16. Value is 20.",
                            "response_status": 200,
                        }
                    }
                ],
                "parameters": {"known": {"location": "ABC", "date": "2026-05-16"}},
            },
        },
    }
    selector = RoleProfileSelector()
    role = selector.select(node_id="fallback_generation", state=state).to_dict()
    assert role["role_id"] in {"information_retrieval_agent", "integration_builder_agent", "code_generation_agent"}

    reduced = RoleScopedContextReducer().reduce_state(state=state, capability_result={}, role_profile=role)
    assert "api_discovery" not in str(reduced["previous_results"])
    assert len(str(reduced)) < 10000
