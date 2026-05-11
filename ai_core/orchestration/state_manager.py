class StateManager:
    @staticmethod
    def initialize(initial_state: dict | None = None) -> dict:
        return dict(initial_state or {})

    @staticmethod
    def merge(current: dict, update: dict) -> dict:
        merged = dict(current)
        merged.update(update)
        return merged
