import unittest

from ai_core.runtime.prompt_optimizer import PromptOptimizer
from ai_core.runtime.workflow_expander import WorkflowExpander


class RuntimeComponentsTest(unittest.TestCase):
    def test_prompt_optimizer_adds_guardrail(self):
        optimized = PromptOptimizer().optimize("base", {"hallucination": True})
        self.assertIn("Do not hallucinate.", optimized)

    def test_workflow_expander_adds_tool_builder_when_missing_tool(self):
        workflow = {"nodes": [{"id": "a", "type": "intent"}]}
        expanded = WorkflowExpander().expand(workflow, {"missing_tool": True})

        self.assertEqual(expanded["nodes"][-1]["id"], "tool_generation")


if __name__ == "__main__":
    unittest.main()
