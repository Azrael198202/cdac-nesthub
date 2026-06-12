from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class KnownStateClassifier:
    """Separates executable parameters from semantic knowledge.

    Execution known tells the runtime whether a step has enough parameters to
    run. Semantic known tells the runtime whether factual content has already
    been verified from trusted material. Descriptive metadata must not be used
    as either verified fact or as permission to generate factual output.
    """

    metadata_keys: frozenset[str] = frozenset({
        "title", "summary", "description", "objective", "intent_summary",
        "original_input", "original_user_input", "user_input", "raw_input",
        "instruction", "prompt", "task_name", "display_name", "name",
        "classified_intent", "intent_type", "recognized_intent", "language",
    })
    semantic_container_keys: frozenset[str] = frozenset({
        "verified_facts", "source_materials", "evidence_items", "citations",
        "references", "provenance", "source_cards", "extracted_materials",
    })

    def split(self, payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
        payload = payload if isinstance(payload, dict) else {}
        execution_known: dict[str, Any] = {}
        semantic_known: dict[str, Any] = {"verified_facts": [], "source_materials": [], "unknowns": []}
        task_metadata: dict[str, Any] = {}
        for key, value in payload.items():
            if value in (None, "", [], {}):
                continue
            normalized = self._normalize_key(key)
            if normalized in self.metadata_keys:
                task_metadata[str(key)] = value
                continue
            if normalized in self.semantic_container_keys:
                semantic_known[str(key)] = value
                continue
            if self._looks_verified_semantic(normalized, value):
                semantic_known[str(key)] = value
                continue
            if self._is_executable_parameter(normalized, value):
                execution_known[str(key)] = value
            else:
                task_metadata[str(key)] = value
        return {
            "execution_known": execution_known,
            "semantic_known": semantic_known,
            "task_metadata": task_metadata,
        }

    def merge_execution_known(self, *payloads: dict[str, Any] | None) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for payload in payloads:
            split = self.split(payload)
            merged.update(split["execution_known"])
            explicit = payload.get("execution_known") if isinstance(payload, dict) and isinstance(payload.get("execution_known"), dict) else {}
            for key, value in explicit.items():
                if value not in (None, "", [], {}):
                    merged[str(key)] = value
        return merged

    def merge_semantic_known(self, *payloads: dict[str, Any] | None) -> dict[str, Any]:
        merged: dict[str, Any] = {"verified_facts": [], "source_materials": [], "unknowns": []}
        for payload in payloads:
            if not isinstance(payload, dict):
                continue
            split = self.split(payload)
            explicit = payload.get("semantic_known") if isinstance(payload.get("semantic_known"), dict) else {}
            for source in (split["semantic_known"], explicit):
                for key, value in source.items():
                    if value in (None, "", [], {}):
                        continue
                    if isinstance(merged.get(key), list) and isinstance(value, list):
                        merged[key].extend(value)
                    else:
                        merged[str(key)] = value
        return merged

    def has_verified_semantic_material(self, semantic_known: dict[str, Any] | None) -> bool:
        semantic_known = semantic_known if isinstance(semantic_known, dict) else {}
        for key in self.semantic_container_keys:
            value = semantic_known.get(key)
            if isinstance(value, list) and value:
                return True
            if isinstance(value, dict) and value:
                return True
        return False

    def _normalize_key(self, key: Any) -> str:
        return str(key or "").strip().lower().replace("-", "_").replace(" ", "_")

    def _is_executable_parameter(self, key: str, value: Any) -> bool:
        if key in self.metadata_keys or key in self.semantic_container_keys:
            return False
        if isinstance(value, (int, float, bool)):
            return True
        if isinstance(value, list):
            return all(not isinstance(item, dict) for item in value)
        if isinstance(value, dict):
            nested_keys = {self._normalize_key(k) for k in value.keys()}
            if nested_keys & self.semantic_container_keys:
                return False
            if nested_keys & self.metadata_keys and len(nested_keys - self.metadata_keys) == 0:
                return False
            return True
        text = str(value).strip()
        if not text:
            return False
        return len(text) <= 240

    def _looks_verified_semantic(self, key: str, value: Any) -> bool:
        if key.startswith("verified_") or key.endswith("_evidence") or key.endswith("_material"):
            return True
        if isinstance(value, dict):
            return bool({self._normalize_key(k) for k in value.keys()} & self.semantic_container_keys)
        return False
