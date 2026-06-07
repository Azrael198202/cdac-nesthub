from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auxiliary_brain.studio.instruction_workflow_planner import InstructionWorkflowPlanner
from ai_core.model_orchestration import BrainModelRouter, LiteLLMBrainClient


def test_duplicate_logical_participants_are_not_selected_twice():
    planner = InstructionWorkflowPlanner()
    participants = [
        {"participant_id": "p1", "display_name": "Reusable Agent", "capability_profile": {"capability_type": "runtime_registered_tool", "tool_id": "tool_a"}},
        {"participant_id": "p2", "display_name": "Reusable Agent", "capability_profile": {"capability_type": "runtime_registered_tool", "tool_id": "tool_a"}},
    ]
    semantic_plan = {
        "steps": [
            {"id": "step_1", "objective": "run", "instruction_fragment": "run", "depends_on": [], "route": {"participant_name": "Reusable Agent"}}
        ]
    }
    plan = planner.plan(instruction="run", participants=participants, graph_id="graph_test", new_id_fn=lambda prefix: prefix + "_x", semantic_plan=semantic_plan)
    assert len(plan.selected_participants) == 1
    assert len([t for t in plan.tasks if t.get("participant_display_name") == "Reusable Agent"]) == 1


def test_brain_model_router_selects_policy_without_hardcoded_callsite_model():
    route = BrainModelRouter().select(brain="repair_brain", task_type="root_cause_analysis", complexity="high")
    assert route.brain == "repair_brain"
    assert route.model
    assert route.provider
    assert route.fallback
    client = LiteLLMBrainClient()
    assert client._litellm_model(route)
    attempts = client._route_attempts(route)
    assert len(attempts) >= 2
    assert attempts[0].provider == route.provider
    assert attempts[1].provider


if __name__ == "__main__":
    test_duplicate_logical_participants_are_not_selected_twice()
    test_brain_model_router_selects_policy_without_hardcoded_callsite_model()
    print("ok")
