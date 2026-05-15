from __future__ import annotations

import json
from typing import Any


class TokenEstimator:
    """Small, dependency-free token estimator for runtime budgeting.

    The estimator is intentionally approximate so ai_core does not depend on
    any provider-specific tokenizer. Runtime/model-specific tokenizers may be
    registered later outside ai_core.
    """

    CHARS_PER_TOKEN = 4

    def estimate_text(self, text: str | None) -> int:
        if not text:
            return 0
        return max(1, int(len(text) / self.CHARS_PER_TOKEN) + 1)

    def estimate_obj(self, value: Any) -> int:
        try:
            text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            text = str(value)
        return self.estimate_text(text)
