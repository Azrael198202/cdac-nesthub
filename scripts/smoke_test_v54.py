import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_core.sandbox.verified_sandbox_runtime import VerifiedSandboxRuntime
from ai_core.workflow.planning_recovery import PlanningRecoveryService
from ai_core.research.model_candidate_evaluator import ModelCandidateEvaluator

artifact = {
    "tool_id": "generic_echo_tool",
    "manifest": {"implementation": {"module_path": "tool.py", "function": "run"}},
    "files": {"tool.py": "def run(payload):\n    return {'status': 'success', 'data': {'echo': payload.get('value')}}\n"},
}
verification = VerifiedSandboxRuntime().verify_tool_artifact(artifact=artifact, test_input={"value": "ok"})
assert verification["safe_to_register"], verification

plan = PlanningRecoveryService().recover_if_empty(workflow_plan={"planned_steps": []}, user_input="Check something from an external source", previous_results={})
assert plan["planned_steps"] and plan["planned_steps"][0]["execution_ready"] is True

model_eval = ModelCandidateEvaluator().evaluate({"model_id": "example-7b-instruct", "tags": ["license:apache-2.0"], "pipeline_tag": "text-generation"})
assert model_eval["estimated_hardware"]["estimated_min_vram_gb"] == 8
print("v54 smoke ok")
