from auxiliary_brain.runtime.execution.reuse_policy import ExecutionReusePolicyClassifier
from auxiliary_brain.task_compiler import TaskGraphCompiler


def test_reuse_policy_classifies_direct_dynamic_and_hybrid_without_names():
    classifier = ExecutionReusePolicyClassifier()
    graph = {
        "task_name": "generic_task",
        "tasks": [
            {"participant_id": "a", "source_contract": {"requires_source_material": False}},
            {"participant_id": "b", "source_contract": {"requires_source_material": True}},
        ],
    }

    classified = classifier.apply_to_task_graph(graph)

    assert classified["tasks"][0]["execution_reuse_policy"]["mode"] == "compiled_direct"
    assert classified["tasks"][1]["execution_reuse_policy"]["mode"] == "dynamic_refresh"
    assert classified["execution_reuse_policy"]["mode"] == "hybrid"
    assert classified["execution_reuse_policy"]["generic"] is True


def test_compiler_persists_reuse_policy_in_manifest_and_steps(tmp_path):
    compiler = TaskGraphCompiler(generated_root=tmp_path)
    graph = {
        "task_name": "generic_compiled_task",
        "graph_id": "generic_compiled_task",
        "tasks": [
            {
                "participant_id": "step_a",
                "source_instruction_fragment": "Execute the locked runtime action.",
                "source_contract": {"requires_source_material": False},
            }
        ],
    }

    compiled = compiler.compile(graph)

    assert compiled["manifest"]["execution_reuse_policy"]["mode"] == "compiled_direct"
    assert compiled["steps"][0]["execution_reuse_policy"]["mode"] == "compiled_direct"
    assert compiled["execution_plan"]["execution_reuse_policy"]["mode"] == "compiled_direct"
    assert compiled["execution_plan"]["steps"][0]["execution_reuse_policy"]["mode"] == "compiled_direct"
