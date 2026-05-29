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

    async def build_contract_runtime(self, *, definition_instruction: str, execution_objective: str, participant_name: str) -> dict[str, Any]:
        """Create a parameter contract at runtime from the agent definition.

        The runtime LLM infers which values the agent must receive later. This
        keeps business/domain requirements out of source/config files. Every
        parameter uses list values so a UI can collect one or many values with
        Continue / Done semantics.
        """
        objective_text = execution_objective or definition_instruction
        if self._looks_like_self_contained_runtime_observation(objective_text):
            return {
                "contract_type": "agent_parameter_contract",
                "source": "self_contained_runtime_observation",
                "parameters": [],
                "missing_information": [],
            }

        prompt_payload = {
            "participant_name": participant_name,
            "definition_instruction": definition_instruction,
            "execution_objective": execution_objective,
            "requirements": {
                "infer_required_parameters": True,
                "all_values_must_be_lists": True,
                "do_not_fill_missing_values": True,
                "use_generic_lower_snake_case_names": True,
            },
        }
        schema = {
            "type": "object",
            "required": ["parameters"],
            "properties": {
                "parameters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["name", "label", "description", "required", "values"],
                        "properties": {
                            "name": {"type": "string"},
                            "label": {"type": "string"},
                            "description": {"type": "string"},
                            "required": {"type": "boolean"},
                            "values": {"type": "array"},
                        },
                        "additionalProperties": True,
                    },
                }
            },
            "additionalProperties": True,
        }
        try:
            from ai_core.llm.provider_router import ProviderRouter
            import asyncio
            result = await asyncio.wait_for(
                ProviderRouter().generate_json(
                    run_id="agent_parameter_contract",
                    node_id="agent_parameter_contract",
                    adapter={
                        "adapter_id": "agent_parameter_contract_adapter",
                        "provider_route": ["ollama", "openai"],
                        "route_name": "input_parsing",
                        "provider_timeout_seconds": 45,
                        "max_provider_attempts": 1,
                        "max_prompt_tokens": 520,
                        "max_schema_chars": 900,
                        "provider_options": {"temperature": 0, "num_predict": 256, "num_ctx": 1536, "think": False},
                    },
                    prompt={
                        "system": (
                            "Return JSON only. Infer required runtime parameters for executing this agent later. "
                            "Do not execute, plan, or name tools. Use generic snake_case names. "
                            "Every parameter values field is an array. Fill explicit values only."
                        )
                    },
                    rendered_user_prompt=json.dumps(prompt_payload, ensure_ascii=False, separators=(",", ":")),
                    schema=schema,
                ),
                timeout=55,
            )
            normalized = self._normalize_contract_result(result, source="runtime_llm")
            objective_text = execution_objective or definition_instruction
            if not normalized.get("parameters") and self._looks_like_open_capability(objective_text):
                return self._fallback_contract_for_objective(objective_text, source="runtime_llm_empty")
            if self._looks_like_content_output_capability(objective_text):
                normalized = self._ensure_content_output_contract_shape(normalized, source="runtime_llm_enriched")
            return normalized
        except Exception as exc:
            # Safe fallback: keep source/config free of domain-specific slots.
            # For open capability definitions, collect a generic task input at
            # execution time so the runtime pauses instead of running without
            # the values needed for that specific task.
            if self._looks_like_open_capability(execution_objective or definition_instruction):
                contract = self._fallback_contract_for_objective(execution_objective or definition_instruction, source="runtime_llm_unavailable")
                contract["contract_generation_error"] = str(exc)
                return contract
            return {
                "contract_type": "agent_parameter_contract",
                "source": "runtime_llm_unavailable",
                "parameters": [],
                "missing_information": [],
                "contract_generation_error": str(exc),
            }


    def _looks_like_self_contained_runtime_observation(self, text: str) -> bool:
        """Detect requests that can be answered from runtime state alone.

        This is a generic temporal/runtime-state guard. It prevents the UI from
        asking for unrelated reminder/message parameters when the agent profile
        itself already asks for the current runtime value.
        """
        normalized = re.sub(r"\s+", " ", str(text or "").strip().lower())
        if not normalized:
            return False
        current_markers = ("current", "now", "present", "現在", "今", "当前", "现在")
        temporal_markers = ("time", "datetime", "timestamp", "時刻", "時間", "日時", "时间")
        return any(marker in normalized for marker in current_markers) and any(marker in normalized for marker in temporal_markers)


    def _looks_like_open_capability(self, text: str) -> bool:
        """Detect reusable capability definitions without domain keywords.

        A definition phrased as an ability usually needs fresh task-run input
        later. This structural guard prevents empty parameter contracts when the
        runtime LLM is unavailable, while avoiding hard-coded business slots.
        """
        normalized = re.sub(r"\s+", " ", str(text or "").strip().lower())
        if not normalized:
            return False
        open_markers = (
            "can ",
            "able to ",
            "capable of ",
            "support ",
            "supports ",
            "handle ",
            "handles ",
        )
        return normalized.startswith(open_markers) or any(f" {marker}" in normalized for marker in open_markers)


    def _fallback_contract_for_objective(self, text: str, *, source: str) -> dict[str, Any]:
        """Build a safe generic fallback when runtime model inference fails.

        The fallback is based on capability shape, not on project/business
        vocabulary. If the agent is defined as producing user-facing text, the
        UI collects reusable content constraints instead of a single opaque
        task_input field. Other open capabilities keep the generic field.
        """
        if self._looks_like_content_output_capability(text):
            contract = {
                "contract_type": "agent_parameter_contract",
                "source": source,
                "parameters": self._content_output_parameters(),
                "collection_policy": {"blocking": True, "scope": "task_run"},
            }
            contract["missing_information"] = self.missing_parameters({"parameter_contract": contract})
            return contract
        return self._open_capability_fallback_contract(source=source)


    def _content_output_parameters(self) -> list[dict[str, Any]]:
        """Generic parameter shape for user-facing content deliverables.

        These slots describe output constraints, not any business domain. They
        keep open-ended content agents from collapsing to one opaque input and
        give the UI enough fields for repeatable execution.  They are execution
        blocking because a content producer cannot create the requested output
        without task-run constraints.
        """
        records = [
            self._parameter_record(name="subject", label="Subject", description="Main subject or request to produce.", required=True, values=[]),
            self._parameter_record(name="size_constraint", label="Size constraint", description="Required size, amount, or length constraint.", required=True, values=[]),
            self._parameter_record(name="style_constraint", label="Style constraint", description="Requested tone, style, or output format.", required=True, values=[]),
            self._parameter_record(name="audience_context", label="Audience context", description="Target reader, user, or recipient context.", required=True, values=[]),
            self._parameter_record(name="output_language", label="Output language", description="Language for the final output.", required=False, values=[]),
            self._parameter_record(name="source_policy", label="Source policy", description="Whether references, evidence, or citations are required.", required=True, values=[]),
        ]
        for record in records:
            if record.get("required"):
                record["runtime_required"] = True
                record["blocking"] = True
                record["execution_required"] = True
        return records

    def _ensure_content_output_contract_shape(self, contract: dict[str, Any], *, source: str) -> dict[str, Any]:
        """Enrich sparse model-inferred contracts for content output agents.

        The model may return only a single vague field. For reusable agents that
        produce user-facing content, a minimal output-constraint contract is more
        reliable and still domain-neutral. Existing explicit model fields/values
        are preserved and generic missing constraint slots are appended.
        """
        if not isinstance(contract, dict):
            contract = {}
        params = contract.get("parameters") if isinstance(contract.get("parameters"), list) else []
        generic = self._content_output_parameters()
        existing_by_name = {str(p.get("name") or "").casefold(): p for p in params if isinstance(p, dict)}
        vague_names = {"task_input", "input", "subject", "request"}
        sparse = len(params) < 3 or all(str(p.get("name") or "").casefold() in vague_names for p in params if isinstance(p, dict))
        if not sparse:
            contract["missing_information"] = self.missing_parameters({"parameter_contract": contract})
            return contract
        merged: list[dict[str, Any]] = []
        used: set[str] = set()
        for gp in generic:
            name = str(gp.get("name") or "").casefold()
            existing = existing_by_name.get(name)
            if existing:
                updated = dict(gp)
                updated.update({k: v for k, v in existing.items() if v not in (None, "", [], {}) or k == "values"})
                merged.append(updated)
            else:
                merged.append(gp)
            used.add(name)
        for p in params:
            name = str(p.get("name") or "").casefold()
            if name and name not in used:
                merged.append(p)
                used.add(name)
        enriched = dict(contract)
        enriched["source"] = source
        enriched["parameters"] = merged
        enriched["collection_policy"] = {"blocking": True, "scope": "task_run"}
        enriched["missing_information"] = self.missing_parameters({"parameter_contract": enriched})
        return enriched

    def _looks_like_content_output_capability(self, text: str) -> bool:
        normalized = re.sub(r"\s+", " ", str(text or "").strip().casefold())
        if not normalized:
            return False
        output_verbs = ("write", "compose", "draft", "generate", "create", "produce")
        output_objects = ("text", "content", "document", "message", "post", "summary", "report", "article", "essay", "story")
        return any(re.search(rf"\b{verb}\b", normalized) for verb in output_verbs) and any(re.search(rf"\b{obj}s?\b", normalized) for obj in output_objects)

    def _open_capability_fallback_contract(self, *, source: str) -> dict[str, Any]:
        contract = {
            "contract_type": "agent_parameter_contract",
            "source": source,
            "parameters": [
                self._parameter_record(
                    name="task_input",
                    label="Task input",
                    description="Provide the task-specific input values required for this run.",
                    required=True,
                    values=[],
                )
            ],
        }
        contract["missing_information"] = self.missing_parameters({"parameter_contract": contract})
        return contract

    def build_contract(self, *, definition_instruction: str, execution_objective: str, participant_name: str) -> dict[str, Any]:
        # Backward-compatible non-LLM path. It only uses explicit config when
        # supplied by a deployment. Source packages should ship this config empty
        # so business parameters are created at runtime.
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
            parameters.append(self._parameter_record(
                name=name,
                label=str(slot.get("label") or name),
                description=str(slot.get("description") or f"Provide {name}."),
                required=bool(slot.get("required", True)),
                values=values,
            ))
        return self._normalize_contract_result({"parameters": parameters}, source="configured_template" if parameters else "empty_runtime_contract")

    def _normalize_contract_result(self, result: dict[str, Any], *, source: str) -> dict[str, Any]:
        params = result.get("parameters") if isinstance(result, dict) else []
        parameters: list[dict[str, Any]] = []
        if isinstance(params, list):
            for item in params:
                if not isinstance(item, dict):
                    continue
                name = self._safe_name(item.get("name"))
                if not name:
                    continue
                parameters.append(self._parameter_record(
                    name=name,
                    label=str(item.get("label") or name),
                    description=str(item.get("description") or f"Please provide {name}."),
                    required=bool(item.get("required", True)),
                    values=self._normalize_list(item.get("values")),
                ))
        contract = {
            "contract_type": "agent_parameter_contract",
            "source": source,
            "parameters": parameters,
        }
        contract["missing_information"] = self.missing_parameters({"parameter_contract": contract})
        return contract

    def _parameter_record(self, *, name: str, label: str, description: str, required: bool, values: list[Any]) -> dict[str, Any]:
        return {
            "name": self._safe_name(name),
            "label": label,
            "description": description,
            "required": required,
            "type": "list",
            "values": values,
            "collection_mode": "repeat_until_done",
        }

    def _safe_name(self, value: Any) -> str:
        name = re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")
        return name[:64]

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
            participant_names = [
                str(participant.get("display_name") or ""),
                str(participant.get("agent_name") or ""),
                str(participant.get("name") or ""),
            ]
            safe_participant_names = [self._safe_name(x) for x in participant_names if str(x).strip()]
            candidates = [f"{pid}.{name}", f"{pid}_{name}", name]
            for prefix in participant_names + safe_participant_names:
                if prefix:
                    candidates.extend([f"{prefix}.{name}", f"{prefix}_{name}"])
            value = None
            lowered = {str(k).casefold(): k for k in provided.keys()}
            for key in candidates:
                if key in provided:
                    value = provided[key]
                    break
                matched = lowered.get(str(key).casefold())
                if matched is not None:
                    value = provided[matched]
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
        pname = str(participant.get("display_name") or participant.get("agent_name") or participant.get("name") or pid or "participant")
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
                "runtime_required": bool(param.get("runtime_required", False)),
                "blocking": bool(param.get("blocking", False)),
                "execution_required": bool(param.get("execution_required", False)),
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
