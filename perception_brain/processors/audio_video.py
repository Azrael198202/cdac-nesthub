from __future__ import annotations

from perception_brain.contracts import ArtifactObservation
from perception_brain.processors.base import BasePerceptionProcessor


class AudioPerceptionProcessor(BasePerceptionProcessor):
    modality = "audio"

    def process(self, artifact: dict) -> ArtifactObservation:
        obs = self._base_observation(artifact, modality="audio")
        path = self._path(artifact)
        if not path:
            obs.status = "unavailable"
            obs.warnings.append("artifact_file_not_found")
            return obs
        try:
            obs.metadata["transcription_mode"] = "optional_runtime_dependency"
            transcript = ""
            try:
                import whisper  # type: ignore
                model = whisper.load_model("base")
                result = model.transcribe(str(path))
                transcript = str(result.get("text") or "")
                obs.metadata["asr_engine"] = "whisper"
            except Exception:
                obs.warnings.append("asr_unavailable")
            obs.extracted_text = self._clip(transcript)
            if transcript.strip():
                summary, warnings = self._summarize_text(text=obs.extracted_text, modality="audio", context={"artifact_id": obs.artifact_id, "filename": obs.name})
                obs.summary = summary
                obs.warnings.extend(warnings)
            else:
                obs.summary = "Audio artifact captured. No transcript was available."
            obs.status = "normalized"
        except Exception as exc:
            obs.status = "failed"
            obs.warnings.append(f"audio_processing_failed:{exc.__class__.__name__}:{exc}")
        return obs


class VideoPerceptionProcessor(BasePerceptionProcessor):
    modality = "video"

    def process(self, artifact: dict) -> ArtifactObservation:
        obs = self._base_observation(artifact, modality="video")
        path = self._path(artifact)
        if not path:
            obs.status = "unavailable"
            obs.warnings.append("artifact_file_not_found")
            return obs
        obs.summary = "Video artifact captured. Keyframe or transcript extraction requires a registered perception capability."
        obs.status = "normalized"
        obs.warnings.append("video_deep_analysis_unavailable")
        return obs
