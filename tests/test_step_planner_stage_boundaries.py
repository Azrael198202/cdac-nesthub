from auxiliary_brain.studio.instruction_workflow_planner import InstructionWorkflowPlanner
from auxiliary_brain.studio.structural_step_planner import StructuralStepPlanner
from auxiliary_brain.delegation.task_mind_graph import TaskMindGraphBuilder


def test_numbered_steps_create_clean_three_stage_dataflow_without_polluting_agent_objectives():
    participants = [
        {"participant_id": "weather_node", "display_name": "Weather Agent", "execution_objective": "original profile"},
        {"participant_id": "time_node", "display_name": "Time Agent", "execution_objective": "original profile"},
    ]
    instruction = (
        "Step 1: Call the Weather Agent. "
        "Step 2: Call the Time Agent. "
        "Step 3: Translate BOTH outputs from Weather Agent and Time Agent into English. "
        "Step 4: Return ONLY the translated English result"
    )
    counter = {"n": 0}

    def new_id(prefix: str) -> str:
        counter["n"] += 1
        return f"{prefix}_{counter['n']}"

    plan = InstructionWorkflowPlanner().plan(
        instruction=instruction,
        participants=participants,
        graph_id="graph",
        new_id_fn=new_id,
        semantic_plan=None,
    )

    assert [task["step_type"] for task in plan.tasks] == [
        "participant_execution",
        "participant_execution",
        "semantic_intermediate_step",
        "semantic_intermediate_step",
    ]
    assert plan.tasks[0]["source_instruction_fragment"] == "Call the Weather Agent"
    assert plan.tasks[1]["source_instruction_fragment"] == "Call the Time Agent"
    assert set(plan.tasks[2]["depends_on"]) == {"weather_node", "time_node"}
    assert plan.tasks[3]["depends_on"] == ["generated_step_3"]

    graph = TaskMindGraphBuilder().build({"tasks": plan.tasks, "instruction": instruction}, plan.selected_participants)
    assert graph["execution_plan"]["groups"] == [["weather_node", "time_node"], ["participant_1"], ["participant_2"]]
    objectives = {node["node_id"]: node["objective"] for node in graph["nodes"]}
    assert objectives["weather_node"] == "Weather Agent"
    assert objectives["time_node"] == "Time Agent"
    assert objectives["participant_1"] == "Translate BOTH outputs from Weather Agent and Time Agent into English"
    assert objectives["participant_2"] == "Return ONLY the translated English result"


def test_short_participant_ids_are_not_matched_inside_common_words():
    participants = [
        {"participant_id": "w", "display_name": "Weather Agent"},
        {"participant_id": "t", "display_name": "Time Agent"},
    ]
    steps = StructuralStepPlanner().build_steps(
        "Step 1: Call the Weather Agent. Step 2: Call the Time Agent.",
        participants,
    )
    assert [(step["label"], step["depends_on"]) for step in steps] == [("Weather Agent", []), ("Time Agent", [])]
