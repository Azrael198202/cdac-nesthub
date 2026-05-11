class ShortTermMemory:
    def __init__(self):
        self.messages: list[dict] = []

    def add(self, item: dict) -> None:
        self.messages.append(item)
