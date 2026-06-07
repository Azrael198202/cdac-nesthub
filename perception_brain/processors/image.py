from __future__ import annotations

from perception_brain.contracts import ArtifactObservation
from perception_brain.processors.base import BasePerceptionProcessor


class ImagePerceptionProcessor(BasePerceptionProcessor):
    modality = "image"

    def process(self, artifact: dict) -> ArtifactObservation:
        obs = self._base_observation(artifact, modality="image")
        path = self._path(artifact)
        if not path:
            obs.status = "unavailable"
            obs.warnings.append("artifact_file_not_found")
            return obs
        try:
            try:
                from PIL import Image  # type: ignore
                with Image.open(path) as img:
                    obs.metadata.update({"width": img.width, "height": img.height, "format": img.format})
            except Exception:
                obs.warnings.append("image_metadata_reader_unavailable")
            text = ""
            try:
                import pytesseract  # type: ignore
                from PIL import Image  # type: ignore
                text = pytesseract.image_to_string(Image.open(path))
                obs.metadata["ocr_engine"] = "pytesseract"
            except Exception:
                obs.warnings.append("ocr_unavailable")
            obs.extracted_text = self._clip(text)
            if obs.extracted_text.strip():
                summary, warnings = self._summarize_text(text=obs.extracted_text, modality="image", context={"artifact_id": obs.artifact_id, "filename": obs.name})
                obs.summary = summary
                obs.warnings.extend(warnings)
            else:
                obs.summary = "Image artifact captured with metadata. No text extraction was available."
            obs.status = "normalized"
        except Exception as exc:
            obs.status = "failed"
            obs.warnings.append(f"image_processing_failed:{exc.__class__.__name__}:{exc}")
        return obs
