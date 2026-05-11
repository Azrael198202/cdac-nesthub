from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import RUNTIME_CONFIGS


class AutoAnswerEngine:
    def __init__(self) -> None:
        self.loader = ConfigLoader()

    def _rules(self) -> list[dict]:
        data = self.loader.load_yaml(RUNTIME_CONFIGS / "environment" / "auto_answers.yaml")
        if not data.get("enabled", True):
            return []
        return data.get("rules", [])

    def find_answer(self, text: str) -> str | None:
        lower = text.lower()
        for rule in self._rules():
            match = str(rule.get("match", "")).lower()
            if match and match in lower:
                return str(rule.get("answer", ""))
        return None
