from pathlib import Path

from auxiliary_brain.studio.instruction_workflow_planner import InstructionWorkflowPlanner


def _id(prefix):
    _id.count += 1
    return f"{prefix}_{_id.count}"
_id.count = 0


def test_dependent_intermediate_step_is_mapped_from_semantic_graph():
    participants = [
        {"participant_id": "p1", "name": "Alpha Agent"},
        {"participant_id": "p2", "name": "Beta Agent"},
    ]
    semantic_plan = {
        "steps": [
            {"id": "s1", "objective": "Run declared participant step.", "depends_on": [], "route": {"participant_id": "p1"}},
            {"id": "s2", "objective": "Apply requested follow-up operation to s1.", "depends_on": ["s1"], "route": {"requires_generated_step": True}},
        ]
    }
    plan = InstructionWorkflowPlanner().plan(
        instruction="opaque user instruction",
        participants=participants,
        graph_id="graph_x",
        new_id_fn=_id,
        semantic_plan=semantic_plan,
    )
    assert plan.coverage["status"] == "passed"
    assert [task["step_type"] for task in plan.tasks] == ["participant_execution", "semantic_intermediate_step"]
    assert plan.tasks[1]["depends_on"] == ["p1"]
    assert len(plan.generated_participants) == 1


def test_independent_multiple_participants_stay_parallel_ready_from_semantic_graph():
    participants = [
        {"participant_id": "p1", "name": "Alpha Agent"},
        {"participant_id": "p2", "name": "Beta Agent"},
    ]
    semantic_plan = {
        "steps": [
            {"id": "s1", "objective": "Run first declared participant.", "depends_on": [], "route": {"participant_id": "p1"}},
            {"id": "s2", "objective": "Run second declared participant.", "depends_on": [], "route": {"participant_id": "p2"}},
        ]
    }
    plan = InstructionWorkflowPlanner().plan(
        instruction="opaque user instruction",
        participants=participants,
        graph_id="graph_y",
        new_id_fn=_id,
        semantic_plan=semantic_plan,
    )
    assert plan.coverage["status"] == "passed"
    assert [task["step_type"] for task in plan.tasks] == ["participant_execution", "participant_execution"]
    assert all(task.get("depends_on") == [] for task in plan.tasks)
    assert plan.generated_participants == []


def test_planner_source_does_not_contain_vocab_tables():
    source = Path("auxiliary_brain/studio/instruction_workflow_planner.py").read_text()
    forbidden = ["TRANSFORM" + "_VERBS", "DEPENDENCY" + "_MARKERS"]
    assert all(token not in source for token in forbidden)
