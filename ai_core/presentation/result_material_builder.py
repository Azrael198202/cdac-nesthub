from __future__ import annotations

from typing import Any

from ai_core.presentation.result_material import ResultMaterial


class ResultMaterialBuilder:
    """Collects generic execution outputs as intermediate material.

    Execution results are not final answers. They are source material for a
    later presentation/synthesis stage.
    """

    TEXT_KEYS = ("final_answer", "answer", "summary", "message", "text")
    INTERNAL_KEYS = {
        "status",
        "source",
        "requires_human_confirmation",
        "provenance",
        "fallback_attempts",
        "raw",
        "debug",
        "trace",
    }

    def from_execution_step(self, step: dict[str, Any]) -> ResultMaterial:
        result = step.get("result") if isinstance(step.get("result"), dict) else {}
        source = str(result.get("source") or step.get("source") or step.get("step_id") or "runtime")
        status = str(result.get("status") or step.get("status") or "unknown")
        provenance = result.get("provenance") if isinstance(result.get("provenance"), dict) else step.get("provenance")
        if not isinstance(provenance, dict):
            provenance = {}
        quality = self._quality(result)
        content = self._content(result)
        metadata = self._metadata(step, result)
        return ResultMaterial(source=source, status=status, content=content, metadata=metadata, provenance=provenance, quality=quality)

    def _quality(self, result: dict[str, Any]) -> dict[str, Any]:
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        candidates = [result.get("answer_material_quality"), data.get("answer_material_quality")]
        for item in candidates:
            if isinstance(item, dict):
                return dict(item)
        return {}

    def _content(self, result: dict[str, Any]) -> Any:
        for key in self.TEXT_KEYS:
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return {key: value.strip()}
        data = result.get("data")
        if isinstance(data, dict):
            # Prefer structured runtime evidence over pre-composed answer text.
            # Pre-composed text may contain extractor traces; structured evidence
            # can be normalized and validated by the semantic contract engine.
            if isinstance(data.get("normalized_facts"), list):
                return {"normalized_facts": data.get("normalized_facts"), "source_url": data.get("source_url"), "source_title": data.get("source_title")}
            if isinstance(data.get("structured_evidence"), list):
                return {"structured_evidence": data.get("structured_evidence"), "source_url": data.get("source_url"), "source_title": data.get("source_title"), "known_parameters": data.get("known_parameters")}
            public = {k: v for k, v in data.items() if k not in self.INTERNAL_KEYS}
            return public if public else {}
        if data is not None:
            return data
        if result.get("error"):
            return {"error": result.get("error")}
        return {}

    def _metadata(self, step: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        for key in ("step_id", "capability", "component_type", "component_id"):
            value = step.get(key) or result.get(key)
            if value is not None:
                metadata[key] = value
        return metadata
