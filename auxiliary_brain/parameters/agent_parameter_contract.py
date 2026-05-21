from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ParameterSlot:
    name: str
    label: str
    description: str
    required: bool = True
    value_type: str = "list"
    values: list[Any] | None = None


class AgentParameterContractService:
    """Build and validate participant parameter contracts.

    The service is intentionally configuration driven. Domain-specific hints can
    be moved into configs/agent_parameter_contracts.json without changing core
    runtime code. Every parameter is represented as a list so a later task can
    naturally accept one or many values.
    """

    def __init__(self, config_path: str | Path = "configs/agent_parameter_contracts.json") -> None:
        self.config_path = Path(config_path)
        self.config = self._load_config()

    def build_contract(self, *, definition_instruction: str, execution_objective: str, participant_name: str) -> dict[str, Any]:
        text = " ".join([definition_instruction or "", execution_objective or "", participant_name or ""]).strip()
        lowered = text.lower()
        matched_template = self._match_template(lowered)
        slots = matched_template.get("parameters") if matched_template else []
        parameters: list[dict[str, Any]] = []
        extracted = self._extract_known_values(text)
        for slot in slots:
            if not isinstance(slot, dict):
                continue
            name = str(slot.get("name") or "").strip()
            if not name:
                continue
            values = self._normalize_list(extracted.get(name))
            parameters.append({
                "name": name,
                "label": str(slot.get("label") or name),
                "description": str(slot.get("description") or f"Provide {name}."),
                "required": bool(slot.get("required", True)),
                "type": "list",
                "values": values,
                "collection_mode": "repeat_until_done",
            })
        return {
            "contract_type": "agent_parameter_contract",
            "source": "definition_instruction",
            "matched_template": matched_template.get("name") if matched_template else None,
            "parameters": parameters,
            "missing_information": self.missing_parameters({"parameter_contract": {"parameters": parameters}}),
        }

    def missing_parameters(self, participant: dict[str, Any]) -> list[dict[str, Any]]:
        contract = participant.get("parameter_contract") if isinstance(participant.get("parameter_contract"), dict) else {}
        parameters = contract.get("parameters") if isinstance(contract.get("parameters"), list) else []
        missing: list[dict[str, Any]] = []
        for param in parameters:
            if not isinstance(param, dict) or not param.get("required", True):
                continue
            values = self._normalize_list(param.get("values") or participant.get("runtime_parameters", {}).get(param.get("name")))
            if values:
                continue
            missing.append(param)
        return missing

    def apply_values(self, participant: dict[str, Any], provided: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(provided, dict):
            return participant
        contract = participant.get("parameter_contract") if isinstance(participant.get("parameter_contract"), dict) else {}
        params = contract.get("parameters") if isinstance(contract.get("parameters"), list) else []
        pid = str(participant.get("participant_id") or "")
        runtime_parameters = participant.setdefault("runtime_parameters", {})
        for param in params:
            if not isinstance(param, dict):
                continue
            name = str(param.get("name") or "").strip()
            if not name:
                continue
            candidates = [f"{pid}.{name}", name]
            value = None
            for key in candidates:
                if key in provided:
                    value = provided[key]
                    break
            values = self._normalize_list(value)
            if values:
                param["values"] = values
                runtime_parameters[name] = values
        contract["missing_information"] = self.missing_parameters(participant)
        participant["parameter_contract"] = contract
        return participant

    def to_missing_input_fields(self, participant: dict[str, Any]) -> list[dict[str, Any]]:
        pid = str(participant.get("participant_id") or "")
        pname = str(participant.get("name") or pid or "participant")
        fields: list[dict[str, Any]] = []
        for param in self.missing_parameters(participant):
            name = str(param.get("name") or "").strip()
            if not name:
                continue
            fields.append({
                "kind": "agent_parameter_required",
                "field": f"{pid}.{name}",
                "name": f"{pid}.{name}",
                "parameter_name": name,
                "participant_id": pid,
                "participant_name": pname,
                "label": f"{pname} / {param.get('label') or name}",
                "message": str(param.get("description") or f"Please provide {name}."),
                "input_type": "list",
                "required": True,
                "collection_mode": "repeat_until_done",
            })
        return fields

    def _load_config(self) -> dict[str, Any]:
        if self.config_path.exists():
            try:
                loaded = json.loads(self.config_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    return loaded
            except Exception:
                pass
        return {"templates": []}

    def _match_template(self, lowered_text: str) -> dict[str, Any]:
        templates = self.config.get("templates") if isinstance(self.config.get("templates"), list) else []
        for template in templates:
            if not isinstance(template, dict):
                continue
            keywords = [str(x).lower() for x in template.get("keywords") or [] if str(x).strip()]
            if keywords and any(keyword in lowered_text for keyword in keywords):
                return template
        return {}

    def _extract_known_values(self, text: str) -> dict[str, list[str]]:
        values: dict[str, list[str]] = {}
        # Generic temporal expressions; config determines whether a slot named
        # date exists. This keeps parsing rules reusable across agents.
        temporal_tokens = re.findall(r"\b(today|tomorrow|yesterday|tonight|next\s+week|next\s+month)\b", text, flags=re.IGNORECASE)
        if temporal_tokens:
            seen = []
            for token in temporal_tokens:
                normalized = " ".join(token.split()).lower()
                if normalized not in seen:
                    seen.append(normalized)
            values["date"] = seen
        # Generic location phrase pattern such as "for Fukuoka" or "in Tokyo".
        loc_match = re.search(r"\b(?:for|in|at)\s+([A-Z][A-Za-z\- ]+?)(?:\s+(?:today|tomorrow|yesterday|tonight|next\b)|[。.!?,]|$)", text)
        if loc_match:
            candidate = loc_match.group(1).strip()
            if candidate:
                values["location"] = [candidate]
        return values

    def _normalize_list(self, value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return [x for x in value if str(x).strip()]
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            try:
                loaded = json.loads(text)
                if isinstance(loaded, list):
                    return [x for x in loaded if str(x).strip()]
            except Exception:
                pass
            return [part.strip() for part in re.split(r"[,，\n]+", text) if part.strip()]
        return [value]
