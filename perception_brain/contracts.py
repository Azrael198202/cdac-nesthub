from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ArtifactObservation:
    artifact_id: str = ""
    name: str = ""
    path: str = ""
    mime_type: str = ""
    modality: str = "unknown"
    status: str = "observed"
    extracted_text: str = ""
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NormalizedInputPackage:
    original_text: str = ""
    normalized_text: str = ""
    artifacts: list[ArtifactObservation] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    extracted_fields: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["artifacts"] = [item.to_dict() if hasattr(item, "to_dict") else item for item in self.artifacts]
        return payload
