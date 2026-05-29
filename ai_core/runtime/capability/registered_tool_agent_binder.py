from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ai_core.config.paths import RUNTIME_REGISTRY


class RegisteredToolAgentBinder:
    """Bind reusable agent profiles to already-registered runtime capabilities.

    This class is deliberately generic.  It does not know what any capability
    does.  It reads runtime registry metadata, compares the user's agent
    definition to registered tool identifiers/capability labels, and emits an
    agent-side binding contract when one executable tool clearly matches.
    """

    def __init__(self, registry_path: Path | None = None) -> None:
        self.registry_path = registry_path or (RUNTIME_REGISTRY / "tool_registry.json")

    def bind(self, *, instruction: str, participant_name: str) -> dict[str, Any] | None:
        candidates = self._candidate_tools()
        if not candidates:
            return None
        scored = []
        for tool in candidates:
            score = self._score(instruction, tool)
            if score > 0:
                scored.append((score, tool))
        if not scored:
            return None
        scored.sort(key=lambda item: item[0], reverse=True)
        best_score, best = scored[0]
        second_score = scored[1][0] if len(scored) > 1 else 0
        # Require a clear lexical/identifier signal from registry metadata.
        # This avoids silently binding an agent to an unrelated generated tool.
        if best_score < 2 or (second_score and best_score == second_score):
            return None
        tool_id = str(best.get("tool_id") or best.get("name") or "").strip()
        if not tool_id:
            return None
        return {
            "binding_status": "bound_to_registered_runtime_tool",
            "participant_name": participant_name,
            "tool_id": tool_id,
            "capability": best.get("capability"),
            "capabilities": best.get("capabilities") if isinstance(best.get("capabilities"), list) else [],
            "match_score": best_score,
            "match_basis": "runtime_registry_metadata",
            "tool_summary": self._tool_summary(best),
            "parameter_contract": self._parameter_contract_from_input_schema(best, source="registered_tool_input_schema"),
            "execution_policy": self._execution_policy(best),
        }

    def _candidate_tools(self) -> list[dict[str, Any]]:
        registry = self._load_registry()
        out: list[dict[str, Any]] = []
        for key, value in registry.items():
            if not isinstance(value, dict):
                continue
            item = dict(value)
            item.setdefault("tool_id", str(key))
            if self._is_executable(item):
                out.append(item)
        return out

    def _load_registry(self) -> dict[str, Any]:
        if not self.registry_path.exists():
            return {}
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8") or "{}")
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _is_executable(self, spec: dict[str, Any]) -> bool:
        status = str(spec.get("status") or "").lower().strip()
        if status in {"disabled", "pending", "draft", "blueprint_generated", "missing_implementation_blueprint_generated"}:
            return False
        implementation = spec.get("implementation") if isinstance(spec.get("implementation"), dict) else {}
        impl_type = str(implementation.get("type") or "").lower().strip()
        if impl_type not in {"python_function", "python_module", "runtime_python", "runtime_provider"}:
            return False
        verification = spec.get("verification") if isinstance(spec.get("verification"), dict) else {}
        return bool(verification.get("sandbox_verification")) or status in {"enabled", "active", "approved", "ready"}

    def _score(self, instruction: str, tool: dict[str, Any]) -> int:
        instruction_tokens = self._tokens(instruction)
        if not instruction_tokens:
            return 0
        labels = [
            tool.get("tool_id"),
            tool.get("name"),
            tool.get("capability"),
        ]
        caps = tool.get("capabilities") if isinstance(tool.get("capabilities"), list) else []
        labels.extend(caps)
        tool_tokens: set[str] = set()
        for label in labels:
            tool_tokens.update(self._tokens(label))
        overlap = instruction_tokens & tool_tokens
        if not overlap:
            return 0
        # Exact label fragments are a stronger signal than incidental token
        # overlap.  The labels are generated runtime metadata, not core logic.
        normalized_instruction = "_".join(sorted(instruction_tokens))
        phrase_bonus = 0
        for label in labels:
            label_tokens = self._tokens(label)
            if len(label_tokens) >= 2 and label_tokens.issubset(instruction_tokens):
                phrase_bonus += 2
            if str(label or "").strip().lower() in normalized_instruction:
                phrase_bonus += 1
        status_bonus = 1 if str(tool.get("status") or "").lower() in {"enabled", "active", "approved", "ready"} else 0
        return len(overlap) + phrase_bonus + status_bonus

    def _tokens(self, value: Any) -> set[str]:
        text = str(value or "").casefold()
        raw = re.split(r"[^a-z0-9]+", text)
        return {x for x in raw if len(x) >= 2}

    def _tool_summary(self, spec: dict[str, Any]) -> dict[str, Any]:
        return {
            "tool_id": spec.get("tool_id"),
            "name": spec.get("name"),
            "capability": spec.get("capability"),
            "capabilities": spec.get("capabilities") if isinstance(spec.get("capabilities"), list) else [],
            "status": spec.get("status"),
            "input_schema": spec.get("input_schema") if isinstance(spec.get("input_schema"), dict) else {},
            "connection_schema": spec.get("connection_schema") if isinstance(spec.get("connection_schema"), dict) else {},
            "secret_schema": spec.get("secret_schema") if isinstance(spec.get("secret_schema"), dict) else {},
            "approval_policy": spec.get("approval_policy") if isinstance(spec.get("approval_policy"), dict) else {},
        }

    def _parameter_contract_from_input_schema(self, spec: dict[str, Any], *, source: str) -> dict[str, Any]:
        schema = spec.get("input_schema") if isinstance(spec.get("input_schema"), dict) else {}
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        required = {str(x) for x in schema.get("required", []) if str(x).strip()} if isinstance(schema.get("required"), list) else set()
        params: list[dict[str, Any]] = []
        for name, prop in properties.items():
            if not isinstance(prop, dict):
                prop = {}
            # Runtime defaults/options can remain implicit. Required user values
            # are collected from the UI; optional fields are available but not
            # blocking.
            value_type = str(prop.get("type") or "string")
            params.append({
                "name": self._safe_name(name),
                "label": str(prop.get("title") or name),
                "description": str(prop.get("description") or f"Provide {name}."),
                "required": str(name) in required,
                "type": "list" if value_type == "array" else value_type,
                "values": [],
                "collection_mode": "repeat_until_done" if value_type == "array" else "single_value",
                "runtime_required": str(name) in required,
                "blocking": str(name) in required,
                "execution_required": str(name) in required,
                "source_schema_type": value_type,
            })
        approval = spec.get("approval_policy") if isinstance(spec.get("approval_policy"), dict) else {}
        if bool(approval.get("required")):
            params.append({
                "name": "approval_confirmed",
                "label": "Confirm execution",
                "description": "Confirm that the runtime capability may execute for this task run.",
                "required": False,
                "type": "boolean",
                "values": [],
                "collection_mode": "single_value",
                "runtime_required": False,
                "blocking": False,
                "execution_required": False,
                "source_schema_type": "boolean",
            })
        params.append({
            "name": "profile_id",
            "label": "Runtime profile",
            "description": "Optional runtime connection profile id. Defaults to default.",
            "required": False,
            "type": "string",
            "values": [],
            "collection_mode": "single_value",
            "runtime_required": False,
            "blocking": False,
            "execution_required": False,
            "source_schema_type": "string",
        })
        contract = {
            "contract_type": "registered_tool_parameter_contract",
            "source": source,
            "tool_id": spec.get("tool_id"),
            "parameters": params,
            "missing_information": [p for p in params if p.get("required") and not p.get("values")],
            "runtime_scope": "task_run",
        }
        return contract

    def _execution_policy(self, spec: dict[str, Any]) -> dict[str, Any]:
        approval = spec.get("approval_policy") if isinstance(spec.get("approval_policy"), dict) else {}
        return {
            "execution_method": "runtime_registered_tool",
            "requires_approval": bool(approval.get("required")),
            "approval_policy": approval,
            "connection_required": bool((spec.get("connection_schema") or {}).get("required")) if isinstance(spec.get("connection_schema"), dict) else False,
            "secret_required": bool((spec.get("secret_schema") or {}).get("required")) if isinstance(spec.get("secret_schema"), dict) else False,
        }

    def _safe_name(self, value: Any) -> str:
        return re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")[:64]
