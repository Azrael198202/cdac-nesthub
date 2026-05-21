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
            if key == "context" and isinstance(value, dict):
                if node_id == "input_parsing":
                    context = self._compact_input_context(value)
                else:
                    context = self._compact_runtime_context(value)
                if context:
                    compact[key] = context
                continue
            if key in self.KEEP_INPUT_KEYS:
                compact[key] = self._compact_value(value, max_depth=2)
                continue
            # Preserve scalar user-provided values without hardcoding domain names.
            if isinstance(value, (str, int, float, bool)) or value is None:
                compact[key] = value
        if node_id == "input_parsing":
            # The first stage should parse the participant's own request only.
            # Coordination graphs, dependency plans, peer results, and execution
            # traces belong to graph scheduling / context-awareness / synthesis.
            # Including them here makes local JSON models emit malformed JSON.
            return compact
        return compact

    def _compact_input_context(self, value: dict[str, Any]) -> dict[str, Any]:
        keep_scalars = {
            "task_graph_id",
            "participant_count",
            "relationship",
            "relation",
            "execution_group",
        }
        out: dict[str, Any] = {}
        for key in keep_scalars:
            item = value.get(key)
            if isinstance(item, (str, int, float, bool)) or item is None:
                out[key] = item
        policy = value.get("participant_dependency_policy")
        if isinstance(policy, dict):
            out["participant_dependency_policy"] = {
                str(k): v for k, v in policy.items()
                if isinstance(v, (str, int, float, bool)) or v is None
            }
        node = value.get("own_mind_graph_node")
        if isinstance(node, dict):
            out["own_mind_graph_node"] = {
                k: node.get(k)
                for k in ("node_id", "node_type", "name", "objective", "relation", "depends_on")
                if k in node
            }
        # Never include full task_mind_graph, participant_dependency_plan,
        # available_peer_results, traces, or previous result payloads in
        # input_parsing. Dependent agents receive peer summaries only in later
        # context-aware stages.
        return out

    def _compact_runtime_context(self, value: dict[str, Any]) -> dict[str, Any]:
        out = self._compact_input_context(value)
        peer_results = value.get("available_peer_results")
        if isinstance(peer_results, list):
            safe: list[Any] = []
            for item in peer_results[:5]:
                if isinstance(item, dict):
                    safe.append(self._compact_value(item, max_depth=2))
            if safe:
                out["available_peer_results"] = safe
        return out

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
        if not s:
            return None
        # Accept either a pure JSON payload or an instruction prefix followed by
        # a JSON envelope. Delegation messages commonly include a short generic
        # instruction before the canonical envelope. Do not send that whole text
        # to early JSON stages when the envelope can be extracted safely.
        candidates: list[str] = []
        if s[0] in "[{":
            candidates.append(s)
        extracted = self._extract_last_json_object(s)
        if extracted and extracted not in candidates:
            candidates.append(extracted)
        for candidate in candidates:
            try:
                return json.loads(candidate)
            except Exception:
                continue
        return None

    def _extract_last_json_object(self, text: str) -> str | None:
        end = text.rfind("}")
        if end < 0:
            return None
        depth = 0
        in_string = False
        escape = False
        for idx in range(end, -1, -1):
            ch = text[idx]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
                continue
            if ch == "}":
                depth += 1
            elif ch == "{":
                depth -= 1
                if depth == 0:
                    return text[idx:end + 1]
        return None
