class LongTermMemory:
    def __init__(self):
        self.records: list[dict] = []

    def add(self, item: dict) -> None:
        self.records.append(item)
