from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_CONFIGS


@dataclass
class SourceRetrievalSettings:
    routing_mode: str = "fallback"  # fixed | fallback | consensus
    engine_order: list[str] | None = None
    verification_threshold: float = 0.8
    max_engines_per_request: int = 3

    def normalized(self) -> "SourceRetrievalSettings":
        allowed_modes = {"fixed", "fallback", "consensus"}
        mode = str(self.routing_mode or "fallback").strip().lower()
        if mode not in allowed_modes:
            mode = "fallback"
        order = self.engine_order if isinstance(self.engine_order, list) else None
        cleaned: list[str] = []
        for item in order or ["google", "bing", "duckduckgo"]:
            engine_id = str(item or "").strip().lower()
            aliases = {"ddg": "duckduckgo", "google_custom_search": "google", "google_cse": "google", "bing_api": "bing"}
            engine_id = aliases.get(engine_id, engine_id)
            if engine_id in {"google", "bing", "duckduckgo"} and engine_id not in cleaned:
                cleaned.append(engine_id)
        if not cleaned:
            cleaned = ["google", "bing", "duckduckgo"]
        try:
            threshold = float(self.verification_threshold)
        except Exception:
            threshold = 0.8
        threshold = max(0.0, min(1.0, threshold))
        try:
            max_engines = int(self.max_engines_per_request)
        except Exception:
            max_engines = 3
        max_engines = max(1, min(3, max_engines))
        return SourceRetrievalSettings(
            routing_mode=mode,
            engine_order=cleaned,
            verification_threshold=threshold,
            max_engines_per_request=max_engines,
        )


class SourceRetrievalSettingsStore:
    """Runtime-owned source retrieval routing settings.

    This store is intentionally generic.  It configures search-provider routing
    for source retrieval; workflows should not contain provider-specific logic.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (RUNTIME_CONFIGS / "source_retrieval.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def defaults(self) -> SourceRetrievalSettings:
        return SourceRetrievalSettings(
            routing_mode="fallback",
            engine_order=["google", "bing", "duckduckgo"],
            verification_threshold=0.8,
            max_engines_per_request=3,
        )

    def load(self) -> SourceRetrievalSettings:
        if not self.path.exists():
            settings = self.defaults().normalized()
            self.save(asdict(settings))
            return settings
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        settings = SourceRetrievalSettings(
            routing_mode=str(payload.get("routing_mode") or "fallback"),
            engine_order=payload.get("engine_order") if isinstance(payload.get("engine_order"), list) else None,
            verification_threshold=payload.get("verification_threshold", 0.8),
            max_engines_per_request=payload.get("max_engines_per_request", 3),
        ).normalized()
        return settings

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        settings = SourceRetrievalSettings(
            routing_mode=str(payload.get("routing_mode") or "fallback"),
            engine_order=payload.get("engine_order") if isinstance(payload.get("engine_order"), list) else None,
            verification_threshold=payload.get("verification_threshold", 0.8),
            max_engines_per_request=payload.get("max_engines_per_request", 3),
        ).normalized()
        data = asdict(settings)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return data

    def engine_order_for_execution(self) -> list[str]:
        settings = self.load()
        order = list(settings.engine_order or [])
        if settings.routing_mode == "fixed":
            return order[:1]
        return order[: settings.max_engines_per_request]

    def as_api_payload(self) -> dict[str, Any]:
        settings = self.load()
        return {
            "routing_mode": settings.routing_mode,
            "engine_order": settings.engine_order or ["google", "bing", "duckduckgo"],
            "verification_threshold": settings.verification_threshold,
            "max_engines_per_request": settings.max_engines_per_request,
            "registered_engines": [
                {"id": "google", "label": "Google", "enabled": True},
                {"id": "bing", "label": "Bing", "enabled": True},
                {"id": "duckduckgo", "label": "DuckDuckGo", "enabled": True},
            ],
        }
