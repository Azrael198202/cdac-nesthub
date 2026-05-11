class VectorStore:
    def __init__(self):
        self.entries: list[dict] = []

    def add(self, item: dict) -> None:
        self.entries.append(item)
