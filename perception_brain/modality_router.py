from __future__ import annotations

from pathlib import Path
from typing import Any


class PerceptionModalityRouter:
    """Classify incoming artifacts by structural file evidence only.

    This router intentionally contains no business-domain handling. It maps
    MIME types and file extensions to generic modalities so processors can turn
    raw user material into an ai_core-friendly normalized input package.
    """

    IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".tif"}
    AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".webm"}
    VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
    DOC_EXT = {".pdf", ".docx", ".doc", ".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".xml", ".xlsx", ".xls"}

    def classify(self, artifact: dict[str, Any]) -> str:
        mime = str(artifact.get("mime_type") or artifact.get("content_type") or "").lower()
        name = str(artifact.get("filename") or artifact.get("name") or artifact.get("path") or "")
        suffix = Path(name).suffix.lower()
        if mime.startswith("image/") or suffix in self.IMAGE_EXT:
            return "image"
        if mime.startswith("audio/") or suffix in self.AUDIO_EXT:
            return "audio"
        if mime.startswith("video/") or suffix in self.VIDEO_EXT:
            return "video"
        if mime.startswith("text/") or suffix in self.DOC_EXT:
            return "document"
        if "pdf" in mime or "word" in mime or "spreadsheet" in mime or "excel" in mime:
            return "document"
        return "unknown"
