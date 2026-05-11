from ai_core.knowledge.rag_service import RAGService


class KnowledgeService:
    def __init__(self):
        self.rag = RAGService()

    def find(self, query: str) -> list[dict]:
        return self.rag.search(query)
