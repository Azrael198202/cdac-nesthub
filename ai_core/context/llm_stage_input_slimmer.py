from __future__ import annotations

import json
from typing import Any


class LLMStageInputSlimmer:
    """Build compact, stage-scoped LLM input without domain/business rules.

    The goal is not to bypass LLM stages. The goal is to avoid sending the full
    delegation envelope, traces, policies, generated artifacts, and repeated
    intermediate payloads to small/local JSON nodes.
    """

    DEFAULT_TEXT_LIMITS = {
        "input_parsing": 1800,
        "intent_recognition": 2600,
        "workflow_planning": 4200,
    }

    DROP_KEYS = {
        "graph_id",
        "community_id",
        "participant_id",
        "participant_count",
        "created_at",
        "updated_at",
        "delivery",
        "trace_path",
        "raw_trace",
        "progress_events",
        "primary_runtime_events",
        "workflow_results",
        "generated_files",
        "runtime_generated",
        "provider_status",
    }

    KEEP_INPUT_KEYS = {
        "request",
        "message",
        "instruction",
        "task_instruction",
        "objective",
        "expected_output",
        "constraints",
        "context",
        "task_name",
        "request_type",
        "participant_name",
    }

    KEEP_POLICY_KEYS = {
        "allow_external_sources",
        "allow_capability_generation",
        "allow_cli",
        "allow_mcp",
        "allow_model_escalation",
        "require_final_user_answer",
        "verified_facts_preferred",
        "auto_approve_read_only",
    }

    KEEP_RESULT_KEYS = {
        "language",
        "original_input",
        "parsed_entities",
        "semantic_modifiers",
        "constraints",
        "temporal_expressions",
        "missing_information",
        "safety_notes",
        "intent_type",
        "intent_summary",
        "normalized_intent",
        "confidence",
        "reason",
        "blocking_missing_information",
        "required_capabilities",
        "execution_strategy",
        "human_interaction",
    }

    def slim_user_input(self, *, node_id: str | None, raw_input: Any, limit: int | None = None) -> str:
        node = str(node_id or "").strip()
        limit = int(limit or self.DEFAULT_TEXT_LIMITS.get(node, 3000))
        payload = self._parse_json(raw_input)
        if isinstance(payload, dict):
            compact = self._compact_input_payload(payload, node_id=node)
            text = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
        elif isinstance(payload, list):
            text = json.dumps(payload[:8], ensure_ascii=False, separators=(",", ":"))
        else:
            text = str(raw_input or "")
        return self._trim(text, limit)

    def slim_previous_results(self, *, node_id: str | None, results: Any, limit: int | None = None) -> dict[str, Any]:
        if not isinstance(results, dict):
            return {}
        node = str(node_id or "").strip()
        limit = int(limit or self.DEFAULT_TEXT_LIMITS.get(node, 3000))
        allowed_nodes = self._allowed_previous_nodes(node)
        compact: dict[str, Any] = {}
        for key in allowed_nodes:
            value = results.get(key)
            if isinstance(value, dict):
                compact[key] = self._keep_known_result_fields(value)
        return self._trim_obj(compact, limit)

    def slim_runtime_context(self, *, node_id: str | None, runtime_context: dict[str, Any]) -> dict[str, Any]:
        keep = {
            "current_datetime_utc",
            "current_date_utc",
            "timezone_hint",
            "locale_hint",
        }
        return {k: v for k, v in (runtime_context or {}).items() if k in keep}

    def _compact_input_payload(self, payload: dict[str, Any], *, node_id: str) -> dict[str, Any]:
        compact: dict[str, Any] = {}
        for key, value in payload.items():
            if key in self.DROP_KEYS:
                continue
            if key == "execution_policy" and isinstance(value, dict):
                policy = {k: value.get(k) for k in self.KEEP_POLICY_KEYS if k in value}
                if policy:
                    compact[key] = policy
                continue
            if key in self.KEEP_INPUT_KEYS:
                compact[key] = self._compact_value(value, max_depth=2)
                continue
            # Preserve scalar user-provided values without hardcoding domain names.
            if isinstance(value, (str, int, float, bool)) or value is None:
                compact[key] = value
        if node_id == "input_parsing":
            # The first stage should understand the user/runtime request, not the
            # entire orchestration envelope.
            return compact
        return compact

    def _allowed_previous_nodes(self, node_id: str) -> list[str]:
        if node_id == "input_parsing":
            return []
        if node_id == "intent_recognition":
            return ["input_parsing"]
        if node_id == "workflow_planning":
            return ["input_parsing", "intent_recognition", "context_awareness"]
        return ["input_parsing", "intent_recognition", "workflow_planning", "execution"]

    def _keep_known_result_fields(self, value: dict[str, Any]) -> dict[str, Any]:
        return {
            key: self._compact_value(item, max_depth=3)
            for key, item in value.items()
            if key in self.KEEP_RESULT_KEYS or key.startswith("_") is False and len(str(item)) < 300
        }

    def _compact_value(self, value: Any, *, max_depth: int) -> Any:
        if max_depth <= 0:
            return self._trim(str(value), 200)
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for index, (key, item) in enumerate(value.items()):
                if index >= 24:
                    out["_truncated"] = True
                    break
                if key in self.DROP_KEYS:
                    continue
                out[str(key)] = self._compact_value(item, max_depth=max_depth - 1)
            return out
        if isinstance(value, list):
            return [self._compact_value(item, max_depth=max_depth - 1) for item in value[:12]]
        if isinstance(value, str):
            return self._trim(" ".join(value.split()), 800)
        return value

    def _trim_obj(self, value: dict[str, Any], limit: int) -> dict[str, Any]:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if len(text) <= limit:
            return value
        return {"_compact_json": self._trim(text, limit), "_truncated": True}

    def _trim(self, text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 24)] + "...[trimmed]"

    def _parse_json(self, raw_input: Any) -> Any:
        if isinstance(raw_input, (dict, list)):
            return raw_input
        if not isinstance(raw_input, str):
            return None
        s = raw_input.strip()
        if not s or s[0] not in "[{":
            return None
        try:
            return json.loads(s)
        except Exception:
            return None
