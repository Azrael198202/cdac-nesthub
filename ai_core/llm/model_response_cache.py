from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_DIR


class ModelResponseCache:
    """Generic model response cache for any provider/model/protocol."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or (RUNTIME_DIR / "cache" / "model_responses")
        self.root.mkdir(parents=True, exist_ok=True)

    def build_key(self, *, provider_name: str, provider: dict[str, Any], payload: dict[str, Any]) -> str:
        stable = {
            "provider_name": provider_name,
            "model": provider.get("model"),
            "protocol": provider.get("protocol") or provider.get("type"),
            "temperature": payload.get("temperature"),
            "response_format": payload.get("response_format"),
            "messages": payload.get("messages"),
            "prompt": payload.get("prompt"),
            "format": payload.get("format"),
        }
        raw = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, key: str) -> dict[str, Any] | None:
        path = self.root / f"{key}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def set(self, key: str, value: dict[str, Any]) -> None:
        path = self.root / f"{key}.json"
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
