from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_DIR


class PromptAuditStore:
    """Append-only audit for model calls.

    The store records minimal, privacy-aware metadata.  It is generic: no task
    domain, provider-specific behavior, or concrete capability logic is encoded.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (RUNTIME_DIR / "logs" / "model_prompt_audit.jsonl")

    def append(
        self,
        *,
        stage_id: str,
        node_id: str | None,
        model: str | None,
        model_source: str | None,
        prompt: str | None,
        output_status: str | None = None,
        route_name: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        text = str(prompt or "")
        record: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "stage_id": str(stage_id or "general_runtime"),
            "node_id": str(node_id or stage_id or "general_runtime"),
            "route_name": str(route_name or ""),
            "model": str(model or ""),
            "model_source": str(model_source or ""),
            "prompt_chars": len(text),
            "prompt_sha256": hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest(),
            "prompt_preview": self._preview(text),
            "output_status": str(output_status or ""),
        }
        if extra:
            record["extra"] = self._safe_extra(extra)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        return record

    def _preview(self, text: str) -> str:
        compact = " ".join(str(text or "").split())
        return compact[:240]

    def _safe_extra(self, value: dict[str, Any]) -> dict[str, Any]:
        safe: dict[str, Any] = {}
        for key, item in value.items():
            if isinstance(item, (str, int, float, bool)) or item is None:
                safe[str(key)] = item
            elif isinstance(item, (list, tuple)):
                safe[str(key)] = [str(x)[:120] for x in item[:10]]
            elif isinstance(item, dict):
                safe[str(key)] = {str(k): str(v)[:120] for k, v in list(item.items())[:20]}
            else:
                safe[str(key)] = str(item)[:120]
        return safe
