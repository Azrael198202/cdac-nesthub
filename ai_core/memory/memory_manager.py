from ai_core.memory.short_term_memory import ShortTermMemory
from ai_core.memory.long_term_memory import LongTermMemory
from ai_core.memory.conversation_store import ConversationStore


class MemoryManager:
    def __init__(self):
        self.short_term = ShortTermMemory()
        self.long_term = LongTermMemory()
        self.conversation = ConversationStore()

    def remember(self, memory_name: str, payload: dict) -> None:
        if memory_name == "short_term":
            self.short_term.add(payload)
        elif memory_name == "long_term":
            self.long_term.add(payload)
        elif memory_name == "conversation_history":
            self.conversation.add(payload)
