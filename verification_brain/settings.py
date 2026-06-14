from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_CONFIGS


@dataclass
class VerificationBrainSettings:
    """User-editable verification brain policy.

    The settings are architecture-level controls.  They do not contain task,
    domain, tool, or business vocabulary, so the same policy can be reused by
    every model-driven stage.
    """

    enabled: bool = True
    verify_model_stages: bool = True
    verify_all_model_stages: bool = False
    max_repair_rounds: int = 3
    minimum_quality: float = 0.86
    minimum_confidence: float = 0.70
    minimum_consensus: float = 0.70
    require_meta_verification: bool = True
    block_stage_on_failure: bool = True
    stage_scope: list[str] = field(default_factory=lambda: [
        "intent_recognition",
        "workflow_planning",
        "agent_action_planning",
        "result_verification",
        "final_synthesis",
        "presentation",
        "presentation_brain",
    ])

    def normalized(self) -> "VerificationBrainSettings":
        self.max_repair_rounds = max(0, min(int(self.max_repair_rounds), 12))
        self.minimum_quality = self._ratio(self.minimum_quality, 0.86)
        self.minimum_confidence = self._ratio(self.minimum_confidence, 0.70)
        self.minimum_consensus = self._ratio(self.minimum_consensus, 0.70)
        self.stage_scope = [str(x).strip() for x in self.stage_scope if str(x).strip()]
        return self

    @staticmethod
    def _ratio(value: Any, default: float) -> float:
        try:
            parsed = float(value)
        except Exception:
            parsed = default
        return max(0.0, min(parsed, 1.0))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self.normalized())


class VerificationBrainSettingsStore:
    """Small JSON-backed settings store used by runtime UI and model loop."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (RUNTIME_CONFIGS / "verification_brain_settings.json")

    def load(self) -> VerificationBrainSettings:
        default = VerificationBrainSettings()
        try:
            if not self.path.exists():
                self.save(default.to_dict())
                return default
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return default
            return VerificationBrainSettings(
                enabled=bool(data.get("enabled", default.enabled)),
                verify_model_stages=bool(data.get("verify_model_stages", default.verify_model_stages)),
                verify_all_model_stages=bool(data.get("verify_all_model_stages", default.verify_all_model_stages)),
                max_repair_rounds=int(data.get("max_repair_rounds", default.max_repair_rounds)),
                minimum_quality=float(data.get("minimum_quality", default.minimum_quality)),
                minimum_confidence=float(data.get("minimum_confidence", default.minimum_confidence)),
                minimum_consensus=float(data.get("minimum_consensus", default.minimum_consensus)),
                require_meta_verification=bool(data.get("require_meta_verification", default.require_meta_verification)),
                block_stage_on_failure=bool(data.get("block_stage_on_failure", default.block_stage_on_failure)),
                stage_scope=data.get("stage_scope") if isinstance(data.get("stage_scope"), list) else list(default.stage_scope),
            ).normalized()
        except Exception:
            return default

    def save(self, payload: dict[str, Any] | VerificationBrainSettings) -> dict[str, Any]:
        settings = payload if isinstance(payload, VerificationBrainSettings) else self._from_payload(payload)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = settings.to_dict()
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return data

    def as_api_payload(self) -> dict[str, Any]:
        return self.load().to_dict()

    def _from_payload(self, payload: dict[str, Any]) -> VerificationBrainSettings:
        current = self.load()
        data = payload if isinstance(payload, dict) else {}
        return VerificationBrainSettings(
            enabled=bool(data.get("enabled", current.enabled)),
            verify_model_stages=bool(data.get("verify_model_stages", current.verify_model_stages)),
            verify_all_model_stages=bool(data.get("verify_all_model_stages", current.verify_all_model_stages)),
            max_repair_rounds=int(data.get("max_repair_rounds", current.max_repair_rounds)),
            minimum_quality=float(data.get("minimum_quality", current.minimum_quality)),
            minimum_confidence=float(data.get("minimum_confidence", current.minimum_confidence)),
            minimum_consensus=float(data.get("minimum_consensus", current.minimum_consensus)),
            require_meta_verification=bool(data.get("require_meta_verification", current.require_meta_verification)),
            block_stage_on_failure=bool(data.get("block_stage_on_failure", current.block_stage_on_failure)),
            stage_scope=data.get("stage_scope") if isinstance(data.get("stage_scope"), list) else list(current.stage_scope),
        ).normalized()
