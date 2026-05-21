from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from ai_core.config.loader import ConfigLoader
from ai_core.config.paths import PROJECT_ROOT
from ai_core.validation.schema_validator import SchemaValidator


class GenericInputParsingExecutor:
    """
    Deterministic first-stage parser.

    This executor intentionally contains no domain/business/task-specific logic.
    It only normalizes the incoming runtime payload into the generic
    input_parsing schema so the runtime does not spend minutes asking a local
    LLM to parse already-structured JSON.
    """

    _TEMPORAL_PATTERNS = [
        (re.compile(r"\b(today)\b", re.IGNORECASE), 0, "date"),
        (re.compile(r"\b(tomorrow)\b", re.IGNORECASE), 1, "date"),
        (re.compile(r"\byesterday\b", re.IGNORECASE), -1, "date"),
        (re.compile(r"\b\d{4}-\d{2}-\d{2}\b"), None, "date"),
    ]

    def __init__(self) -> None:
        self.loader = ConfigLoader()
        self.validator = SchemaValidator()

    async def execute(self, workflow_node: dict, node_config: dict, state: dict, capability_result: dict) -> dict:
        schema = self.loader.load_json(PROJECT_ROOT / node_config["output_schema"])
        raw_input = state.get("input", "")
        parsed_payload = self._try_parse_json(raw_input)
        text_fields = self._extract_text_fields(parsed_payload)
        combined_text = "\n".join([str(raw_input), *text_fields.values()])

        result = {
            "language": self._detect_language(combined_text),
            "original_input": str(raw_input),
            "parsed_entities": self._build_parsed_entities(parsed_payload, text_fields),
            "semantic_modifiers": [],
            "constraints": self._extract_constraints(parsed_payload),
            "temporal_expressions": self._extract_temporal_expressions(combined_text),
            "missing_information": [],
            "safety_notes": [],
            "_executor_type": "generic_input_parsing",
            "_node_id": node_config.get("node_id"),
            "_status": "executed",
        }
        self.validator.validate_data(result, schema)
        return result

    def _try_parse_json(self, value: Any) -> Any:
        if isinstance(value, (dict, list)):
            return value
        if not isinstance(value, str):
            return None
        s = value.strip()
        if not s or s[0] not in "[{":
            return None
        try:
            return json.loads(s)
        except Exception:
            return None

    def _extract_text_fields(self, payload: Any) -> dict[str, str]:
        fields: dict[str, str] = {}
        if isinstance(payload, dict):
            for key, val in payload.items():
                if isinstance(val, str):
                    fields[str(key)] = val
                elif isinstance(val, dict):
                    for sub_key, sub_val in val.items():
                        if isinstance(sub_val, str):
                            fields[f"{key}.{sub_key}"] = sub_val
        return fields

    def _build_parsed_entities(self, payload: Any, text_fields: dict[str, str]) -> dict[str, Any]:
        if isinstance(payload, dict):
            scalar_fields = {
                str(k): v
                for k, v in payload.items()
                if isinstance(v, (str, int, float, bool)) or v is None
            }
            collection_keys = [str(k) for k, v in payload.items() if isinstance(v, (dict, list))]
            return {
                "input_format": "json_object",
                "scalar_fields": scalar_fields,
                "text_fields": text_fields,
                "collection_keys": collection_keys,
            }
        if isinstance(payload, list):
            return {"input_format": "json_array", "item_count": len(payload)}
        return {"input_format": "text"}

    def _extract_constraints(self, payload: Any) -> dict[str, Any]:
        if isinstance(payload, dict):
            constraints = payload.get("constraints")
            if isinstance(constraints, dict):
                return constraints
            policy = payload.get("execution_policy")
            if isinstance(policy, dict):
                return {"execution_policy": policy}
        return {}

    def _extract_temporal_expressions(self, text: str) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc).date()
        items: list[dict[str, Any]] = []
        seen: set[tuple[str, str | None]] = set()
        for pattern, offset_days, value_type in self._TEMPORAL_PATTERNS:
            for m in pattern.finditer(text or ""):
                raw = m.group(0)
                normalized = None
                if offset_days is None and re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
                    normalized = raw
                elif offset_days is not None:
                    normalized = (now + timedelta(days=offset_days)).isoformat()
                key = (raw.lower(), normalized)
                if key in seen:
                    continue
                seen.add(key)
                items.append({"text": raw, "normalized_value": normalized, "value_type": value_type})
        return items

    def _detect_language(self, text: str) -> str:
        if re.search(r"[\u3040-\u30ff]", text or ""):
            return "ja"
        if re.search(r"[\u4e00-\u9fff]", text or ""):
            return "zh"
        return "en"
