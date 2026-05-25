from auxiliary_brain.studio.instruction_workflow_planner import InstructionWorkflowPlanner


def test_explicit_steps_build_three_stage_dataflow_without_collapsing_nodes():
    planner = InstructionWorkflowPlanner()
    participants = [
        {"participant_id": "p_weather", "display_name": "Weather Agent", "agent_name": "Weather Agent"},
        {"participant_id": "p_time", "display_name": "Time Agent", "agent_name": "Time Agent"},
    ]
    result = planner.plan(
        instruction=(
            "Step 1: Call the Weather Agent. "
            "Step 2: Call the Time Agent. "
            "Step 3: Translate BOTH outputs from Weather Agent and Time Agent into English. "
            "Step 4: Return ONLY the translated English result."
        ),
        participants=participants,
        graph_id="g",
        new_id_fn=lambda prefix: f"{prefix}_{len(result_ids)}" if False else "generated_x",
        semantic_plan={"steps": []},
    )
    assert len(result.tasks) == 4
    assert [task["step_type"] for task in result.tasks] == [
        "participant_execution",
        "participant_execution",
        "semantic_intermediate_step",
        "semantic_intermediate_step",
    ]
    assert result.tasks[0]["source_instruction_fragment"] == "Call the Weather Agent"
    assert result.tasks[1]["source_instruction_fragment"] == "Call the Time Agent"
    assert set(result.tasks[2]["depends_on"]) == {"p_weather", "p_time"}
    assert result.tasks[3]["depends_on"] == [result.tasks[2]["source_step_id"]]


def test_structural_plan_overrides_collapsed_semantic_plan_when_it_preserves_more_graph_shape():
    planner = InstructionWorkflowPlanner()
    participants = [
        {"participant_id": "p_weather", "display_name": "Weather Agent", "agent_name": "Weather Agent"},
        {"participant_id": "p_time", "display_name": "Time Agent", "agent_name": "Time Agent"},
    ]
    bad_semantic = {
        "steps": [
            {
                "id": "bad1",
                "objective": "Return ONLY the translated English result",
                "instruction_fragment": "Return ONLY the translated English result",
                "depends_on": [],
                "route": {"requires_generated_step": True},
            },
            {
                "id": "bad2",
                "objective": "Translate BOTH outputs from Weather Agent and Time Agent into English",
                "instruction_fragment": "Translate BOTH outputs from Weather Agent and Time Agent into English",
                "depends_on": ["bad1"],
                "route": {"requires_generated_step": True},
            },
        ]
    }
    ids = iter(["generated_translate", "generated_return"])
    result = planner.plan(
        instruction=(
            "Step 1: Call the Weather Agent. "
            "Step 2: Call the Time Agent. "
            "Step 3: Translate BOTH outputs from Weather Agent and Time Agent into English. "
            "Step 4: Return ONLY the translated English result."
        ),
        participants=participants,
        graph_id="g",
        new_id_fn=lambda prefix: next(ids),
        semantic_plan=bad_semantic,
    )
    assert [task["source_instruction_fragment"] for task in result.tasks] == [
        "Call the Weather Agent",
        "Call the Time Agent",
        "Translate BOTH outputs from Weather Agent and Time Agent into English",
        "Return ONLY the translated English result",
    ]


def test_created_task_selected_ids_follow_task_nodes_including_generated_steps():
    from auxiliary_brain.studio.service import AgentStudioService

    service = AgentStudioService()
    task_graph = {
        "tasks": [
            {"participant_id": "a"},
            {"participant_id": "b"},
            {"participant_id": "c"},
        ],
        "selected_participant_ids": ["a", "b", "c"],
    }
    participants = [
        {"participant_id": "b", "name": "B"},
        {"participant_id": "c", "name": "C"},
        {"participant_id": "a", "name": "A"},
    ]
    ordered = service._participants_for_task_graph(task_graph, participants)
    assert [p["participant_id"] for p in ordered] == ["a", "b", "c"]
