from presentation_brain.failure_message_renderer import FailureMessageRenderer

report = {
    "failure_class": "task_graph_static_validation_failed",
    "stage": "create_task_graph",
    "task_name": "ExampleTask",
    "failed_checks": [
        {
            "failure_class": "agent_reference_not_found",
            "message": "A declared participant reference did not resolve to an existing durable participant.",
            "line": 9,
            "reference": "SendMail Agent",
            "suggestions": ["SendGmail Agent"],
            "level": "create_task_graph",
        },
        {
            "failure_class": "template_reference_not_found",
            "message": "A template reference points to a missing step.",
            "line": 11,
            "reference": "Step99.final_answer",
            "declared_steps": ["Step1", "Step2"],
            "level": "create_task_graph",
        },
    ],
    "suggested_location": ["auxiliary_brain.studio.create_task_graph", "task_graph_static_validation"],
}

renderer = FailureMessageRenderer()
user = renderer.render(report, allow_llm=False, profile="user").to_dict()
advanced = renderer.render(report, allow_llm=False, profile="advanced").to_dict()
developer = renderer.render(report, allow_llm=False, profile="developer").to_dict()
diagnostic = renderer.render(report, allow_llm=False, profile="diagnostic").to_dict()

assert user["technical"].get("presentation_profile") == "user"
assert not user["location"]
assert advanced["location"]
assert developer["technical"].get("failure_class") == "task_graph_static_validation_failed"
assert diagnostic["technical"].get("presentation_profile") == "diagnostic"
print("verify_v22_2_presentation_profiles: passed")
