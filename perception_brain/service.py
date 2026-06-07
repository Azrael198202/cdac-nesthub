from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_GENERATED
from ai_core.model_orchestration import LiteLLMBrainClient
from perception_brain.contracts import ArtifactObservation, NormalizedInputPackage
from perception_brain.modality_router import PerceptionModalityRouter
from perception_brain.processors.audio_video import AudioPerceptionProcessor, VideoPerceptionProcessor
from perception_brain.processors.base import BasePerceptionProcessor
from perception_brain.processors.image import ImagePerceptionProcessor
from perception_brain.processors.text_document import DocumentPerceptionProcessor


class PerceptionBrainService:
    """Normalize raw user input and artifacts before ai_core starts.

    The Perception Brain behaves like a generic sensory gateway. It performs
    modality detection, extraction, and summarization, then emits a standard
    package. It does not decide intent, build workflows, execute tools, or
    contain business-specific shortcuts.
    """

    def __init__(self, *, llm_client: LiteLLMBrainClient | None = None, output_root: Path | None = None) -> None:
        self.llm_client = llm_client or LiteLLMBrainClient()
        self.router = PerceptionModalityRouter()
        self.output_root = output_root or (RUNTIME_GENERATED / "perception")
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.processors: dict[str, BasePerceptionProcessor] = {
            "document": DocumentPerceptionProcessor(llm_client=self.llm_client),
            "image": ImagePerceptionProcessor(llm_client=self.llm_client),
            "audio": AudioPerceptionProcessor(llm_client=self.llm_client),
            "video": VideoPerceptionProcessor(llm_client=self.llm_client),
        }

    def normalize(self, *, text: str, uploaded_artifacts: list[dict[str, Any]] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        artifacts = [item for item in (uploaded_artifacts or []) if isinstance(item, dict)]
        observations: list[ArtifactObservation] = []
        warnings: list[str] = []
        for item in artifacts:
            modality = self.router.classify(item)
            processor = self.processors.get(modality)
            if processor is None:
                obs = ArtifactObservation(
                    artifact_id=str(item.get("artifact_id") or item.get("id") or ""),
                    name=str(item.get("filename") or item.get("name") or "artifact"),
                    path=str(item.get("path") or ""),
                    mime_type=str(item.get("mime_type") or item.get("content_type") or ""),
                    modality=modality,
                    status="unsupported_modality",
                    warnings=["no_generic_processor_available"],
                )
            else:
                obs = processor.process(item)
            observations.append(obs)
            warnings.extend(obs.warnings)

        normalized_text = self._compose_normalized_text(original=text, observations=observations)
        package = NormalizedInputPackage(
            original_text=str(text or ""),
            normalized_text=normalized_text,
            artifacts=observations,
            metadata={
                "created_at": datetime.now(timezone.utc).isoformat(),
                "artifact_count": len(observations),
                "modalities": sorted({obs.modality for obs in observations}),
                "perception_stage": "completed",
            },
            warnings=warnings,
            confidence=self._confidence(observations),
        )
        payload = package.to_dict()
        self._record(payload=payload, context=context or {})
        return payload

    def _compose_normalized_text(self, *, original: str, observations: list[ArtifactObservation]) -> str:
        sections = [str(original or "").strip()]
        if observations:
            sections.append("\n[Perception Brain normalized artifacts]")
        for idx, obs in enumerate(observations, start=1):
            block = [
                f"Artifact {idx}: {obs.name}",
                f"- modality: {obs.modality}",
                f"- status: {obs.status}",
            ]
            if obs.summary:
                block.append(f"- summary: {obs.summary}")
            if obs.extracted_text:
                block.append("- extracted_text:")
                block.append(obs.extracted_text[:3000])
            if obs.warnings:
                block.append(f"- warnings: {', '.join(obs.warnings[:6])}")
            sections.append("\n".join(block))
        return "\n\n".join([s for s in sections if s.strip()])

    def _confidence(self, observations: list[ArtifactObservation]) -> float:
        if not observations:
            return 1.0
        score = 1.0
        for obs in observations:
            if obs.status in {"failed", "unsupported_modality", "unavailable"}:
                score -= 0.18
            if obs.warnings:
                score -= min(0.12, 0.02 * len(obs.warnings))
        return max(0.1, min(1.0, round(score, 3)))

    def _record(self, *, payload: dict[str, Any], context: dict[str, Any]) -> None:
        event = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "context": context,
            "package": payload,
        }
        path = self.output_root / "perception_events.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
