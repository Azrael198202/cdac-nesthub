class PromptOptimizer:
    def optimize(self, prompt_text: str, feedback: dict):
        improved = prompt_text
        if feedback.get("hallucination"):
            improved += "\nDo not hallucinate."
        return improved
