import unittest

from ai_core.orchestration.graph_builder import GraphBuilder


class GraphBuilderTest(unittest.TestCase):
    def test_build_uses_declared_next_edges(self):
        workflow = {
            "nodes": [
                {"id": "a", "type": "intent", "next": "b"},
                {"id": "b", "type": "planner", "next": ["c"]},
                {"id": "c", "type": "output"},
            ]
        }

        graph = GraphBuilder().build(workflow)

        self.assertEqual(graph.nodes, ["a", "b", "c"])
        self.assertEqual(graph.edges, [("a", "b"), ("b", "c")])


if __name__ == "__main__":
    unittest.main()
