class MemoryManager:
    def build_context(self, message: str) -> dict:
        return {"input": message, "short_term": [], "long_term_refs": []}
