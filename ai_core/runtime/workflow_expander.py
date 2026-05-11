class WorkflowExpander:
    def expand(self, workflow: dict, feedback: dict):
        updated = dict(workflow)
        nodes = list(updated.get("nodes", []))

        if feedback.get("missing_tool"):
            nodes.append({"id": "tool_generation", "type": "tool_builder"})

        updated["nodes"] = nodes
        return updated
