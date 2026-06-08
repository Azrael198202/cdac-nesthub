from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ai_core.model_orchestration import LiteLLMBrainClient
from perception_brain.contracts import ArtifactObservation


class BasePerceptionProcessor:
    modality = "unknown"

    def __init__(self, *, llm_client: LiteLLMBrainClient | None = None, max_text_chars: int = 6000) -> None:
        self.llm_client = llm_client or LiteLLMBrainClient()
        self.max_text_chars = max_text_chars

    def process(self, artifact: dict[str, Any]) -> ArtifactObservation:
        raise NotImplementedError

    def _path(self, artifact: dict[str, Any]) -> Path | None:
        raw = str(artifact.get("path") or "").strip()
        if not raw:
            return None
        path = Path(raw)
        return path if path.exists() else None

    def _base_observation(self, artifact: dict[str, Any], *, modality: str | None = None) -> ArtifactObservation:
        path = self._path(artifact)
        meta = {
            "size_bytes": artifact.get("size_bytes"),
            "source": artifact.get("source"),
        }
        if path:
            try:
                meta["filesystem_size_bytes"] = path.stat().st_size
            except Exception:
                pass
        return ArtifactObservation(
            artifact_id=str(artifact.get("artifact_id") or artifact.get("id") or ""),
            name=str(artifact.get("filename") or artifact.get("name") or (path.name if path else "artifact")),
            path=str(path or artifact.get("path") or ""),
            mime_type=str(artifact.get("mime_type") or artifact.get("content_type") or ""),
            modality=modality or self.modality,
            metadata=meta,
        )

    def _clip(self, text: str, limit: int | None = None) -> str:
        limit = int(limit or self.max_text_chars)
        text = str(text or "")
        return text if len(text) <= limit else text[:limit] + "\n...[truncated]"

    def _summarize_text(self, *, text: str, modality: str, context: dict[str, Any] | None = None) -> tuple[str, list[str]]:
        text = self._clip(text, 4000).strip()
        if not text:
            return "", []
        if str(os.environ.get("AI_CORE_PERCEPTION_ENABLE_LLM_SUMMARY") or "").strip().casefold() not in {"1", "true", "yes", "on"}:
            compact = " ".join(text.split())
            return compact[:500], ["llm_summary_skipped:disabled_by_default"]
        prompt = (
            "Summarize the following normalized user artifact for a runtime input parser. "
            "Do not infer business intent. Extract only neutral structure, key facts, and warnings. "
            "Return concise plain text.\n\n"
            f"Modality: {modality}\n"
            f"Content:\n{text}"
        )
        result = self.llm_client.complete_sync(
            brain="perception_brain",
            task_type=f"{modality}_summarization",
            complexity="default",
            messages=[{"role": "user", "content": prompt}],
            context=context or {},
        )
        if result.status == "completed" and result.content.strip():
            return result.content.strip(), []
        return "", [f"llm_summary_unavailable:{result.status}"]

    def _safe_json_preview(self, value: Any) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, indent=2)[: self.max_text_chars]
        except Exception:
            return str(value)[: self.max_text_chars]
