class MemoryManager:
    def build_context(self, message: str) -> dict:
        return {"short_term": [], "long_term_refs": [], "input": message}
