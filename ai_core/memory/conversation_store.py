class ConversationStore:
    def __init__(self):
        self.conversations: list[dict] = []

    def add(self, item: dict) -> None:
        self.conversations.append(item)
