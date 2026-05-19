from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai_core.config.paths import CONFIGS_DIR


class FeedbackClassifier:
    """Classify studio messages as generic runtime feedback.

    Matching terms are externalized to configuration.  The core class only
    understands generic adaptation intents and never embeds domain vocabulary.
    """

    def __init__(self, config_path: str | Path | None = None) -> None:
        self.config_path = Path(config_path) if config_path else CONFIGS_DIR / "agent_studio_commands.json"
        self.config = self._load_config()

    def classify(self, message: str, *, fallback_target: str | None = None) -> dict[str, Any]:
        text = str(message or "").strip()
        lowered = text.lower()
        feedback_config = self.config.get("feedback_intents") if isinstance(self.config.get("feedback_intents"), dict) else {}
        upgrade_terms = [str(x).lower() for x in feedback_config.get("upgrade_quality", [])]
        retry_terms = [str(x).lower() for x in feedback_config.get("retry_or_reoptimize", [])]
        dissatisfaction_terms = [str(x).lower() for x in feedback_config.get("dissatisfaction", [])]
        generic_negative_signals = [
            "doesn't have", "does not have", "missing", "not include", "not included",
            "wrong", "incorrect", "not correct", "not right", "doesn't answer",
            "不对", "没有", "不正确", "不是", "缺少", "重新", "优化", "升级",
        ]
        if any(term and term in lowered for term in upgrade_terms):
            intent = "upgrade_execution_quality"
        elif any(term and term in lowered for term in retry_terms):
            intent = "reoptimize_previous_result"
        elif any(term and term in lowered for term in dissatisfaction_terms) or any(term in lowered for term in generic_negative_signals):
            intent = "reoptimize_previous_result" if (fallback_target or "re" in lowered or "重新" in lowered or "优化" in lowered or "upgrade" in lowered or "升级" in lowered) else "record_result_feedback"
        else:
            return {"matched": False, "intent": "chat", "message": text}
        return {
            "matched": True,
            "intent": intent,
            "message": text,
            "target_task": self._extract_task_name(text) or fallback_target,
            "requested_action": "rerun_with_escalation" if intent in {"upgrade_execution_quality", "reoptimize_previous_result"} else "record_feedback",
            "target_node": "output",
            "quality_signal": "dissatisfied",
        }

    def _load_config(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return {}
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _extract_task_name(self, text: str) -> str | None:
        # Generic task-like identifier extraction.  This intentionally does not
        # encode domain words; it only detects compact identifier tokens.
        import re

        patterns = [
            r"\b((?:task|job|run)[A-Za-z0-9_\-]+)\b",
            r"\b(?:task|job|run)\s*[:=#-]\s*([A-Za-z0-9_\-]+)\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None
