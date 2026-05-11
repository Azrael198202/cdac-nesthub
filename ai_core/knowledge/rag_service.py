class RAGService:
    def search(self, query: str) -> list[dict]:
        return [{"query": query, "source": "rag"}]
