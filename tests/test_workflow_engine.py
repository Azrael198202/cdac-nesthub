import asyncio
import unittest

from ai_core.orchestration.workflow_engine import WorkflowEngine


class WorkflowEngineTest(unittest.TestCase):
    def test_load_default_workflow(self):
        engine = WorkflowEngine(config_root="configs")
        workflow = engine.load_workflow("workflows/default_orchestration.yaml")

        self.assertEqual(workflow["workflow_id"], "default_orchestration")
        self.assertTrue(workflow["nodes"])

    def test_run_processes_nodes(self):
        engine = WorkflowEngine(config_root="configs")
        workflow = {
            "workflow_id": "test",
            "nodes": [
                {"id": "intent_recognition", "type": "intent", "model_group": "intent_models"},
                {"id": "workflow_planning", "type": "planner", "model_group": "planning_models"},
                {"id": "execution", "type": "executor", "tools": ["web_search", "shell"]},
            ],
        }

        result = asyncio.run(engine.run(workflow, {"input": "hello"}))

        self.assertIn("intent", result)
        self.assertIn("plan", result)
        self.assertIn("execution", result)
        self.assertEqual(result["execution"]["executed"], ["web_search", "shell"])


if __name__ == "__main__":
    unittest.main()
