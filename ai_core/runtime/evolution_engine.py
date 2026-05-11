class EvolutionEngine:
    def evolve(self, workflow: dict, feedback: dict) -> dict:
        from ai_core.runtime.workflow_expander import WorkflowExpander

        expander = WorkflowExpander()
        return expander.expand(workflow, feedback)
