from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from ai_core.config.paths import RUNTIME_DIR


class ExecutionStateRepair:
    """
    Repairs runtime-generated workflow state before execution.

    This class is intentionally domain-agnostic. It does not know concrete task
    domains, providers, or business meanings. It only applies structural safety
    rules and runtime-configured refinement-field policies.
    """

    DEFAULT_OPTIONAL_REFINEMENT_FIELDS: set[str] = set()
    DEFAULT_READ_ONLY_ACTION_HINTS: set[str] = set()
    DEFAULT_READ_ONLY_STRATEGY_HINTS: set[str] = set()
    DEFAULT_IRREVERSIBLE_ACTION_HINTS: set[str] = set()

    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path or (RUNTIME_DIR / "configs" / "orchestration" / "execution_state_repair.yaml")
        config = self._load_config(self.config_path)
        self.optional_refinement_fields = set(config.get("optional_refinement_fields") or self.DEFAULT_OPTIONAL_REFINEMENT_FIELDS)
        self.read_only_action_hints = set(config.get("read_only_action_hints") or self.DEFAULT_READ_ONLY_ACTION_HINTS)
        self.irreversible_action_hints = set(config.get("irreversible_action_hints") or self.DEFAULT_IRREVERSIBLE_ACTION_HINTS)
        self.read_only_strategy_hints = set(config.get("read_only_strategy_hints") or self.DEFAULT_READ_ONLY_STRATEGY_HINTS)

    def repair(self, workflow_plan: dict[str, Any], *, runtime_context: dict[str, Any] | None = None) -> dict[str, Any]:
        plan = deepcopy(workflow_plan or {})
        steps = plan.get("planned_steps") if isinstance(plan.get("planned_steps"), list) else []
        repaired_steps: list[dict[str, Any]] = []
        repair_notes = {
            "moved_to_optional": [],
            "execution_ready_changed": [],
            "human_interaction_removed": [],
            "normalized_missing_required": [],
        }

        for raw_step in steps:
            if not isinstance(raw_step, dict):
                continue
            step = deepcopy(raw_step)
            step_id = str(step.get("step_id") or step.get("task_id") or "unknown_step")
            params = step.get("parameters") if isinstance(step.get("parameters"), dict) else {}
            known = params.get("known") if isinstance(params.get("known"), dict) else {}
            optional = params.get("optional") if isinstance(params.get("optional"), dict) else {}
            missing_required = params.get("missing_required")

            missing_names = self._missing_names(missing_required)
            optional_like = [name for name in missing_names if self._is_optional_refinement(name)]
            genuinely_missing = [name for name in missing_names if name not in optional_like]

            if optional_like:
                for name in optional_like:
                    optional[name] = self._missing_value(missing_required, name)
                    repair_notes["moved_to_optional"].append({"step_id": step_id, "field": name})

                if isinstance(missing_required, dict):
                    missing_required = {k: v for k, v in missing_required.items() if str(k) not in optional_like}
                elif isinstance(missing_required, list):
                    missing_required = [v for v in missing_required if str(v) not in optional_like]
                repair_notes["normalized_missing_required"].append({"step_id": step_id, "remaining": genuinely_missing})

            params["known"] = known
            params["optional"] = optional
            params["missing_required"] = missing_required if genuinely_missing else ([] if isinstance(missing_required, list) else {})
            step["parameters"] = params
            step["missing_fields"] = genuinely_missing

            structurally_requires_confirmation = self._requires_confirmation_by_structure(step)

            if not genuinely_missing and not structurally_requires_confirmation:
                # Planner output may set confirmation/execution_ready=false for
                # read-only observation/retrieval steps.  In auto-run contexts,
                # a step with complete parameters and no structural side effect
                # must be executable.  This is a generic execution-state repair;
                # it does not depend on any domain keyword.
                if step.get("execution_ready") is not True:
                    repair_notes["execution_ready_changed"].append({"step_id": step_id, "from": step.get("execution_ready"), "to": True})
                step["execution_ready"] = True
                step["requires_human_confirmation"] = False
                human_interaction = step.get("human_interaction")
                if isinstance(human_interaction, dict) and human_interaction.get("required"):
                    step["human_interaction"] = {"required": False, "type": "none", "fields": {}}
                    repair_notes["human_interaction_removed"].append({"step_id": step_id})

            elif not genuinely_missing and self._can_mark_ready(step):
                if step.get("execution_ready") is not True:
                    repair_notes["execution_ready_changed"].append({"step_id": step_id, "from": step.get("execution_ready"), "to": True})
                step["execution_ready"] = True
                human_interaction = step.get("human_interaction")
                if isinstance(human_interaction, dict) and human_interaction.get("required"):
                    fields = human_interaction.get("fields")
                    if self._human_interaction_only_optional(fields):
                        step["human_interaction"] = {"required": False, "type": "none", "fields": {}}
                        repair_notes["human_interaction_removed"].append({"step_id": step_id})

            if structurally_requires_confirmation:
                step["requires_human_confirmation"] = True
                hi = step.get("human_interaction") if isinstance(step.get("human_interaction"), dict) else {}
                hi.setdefault("required", True)
                hi.setdefault("type", "confirmation")
                step["human_interaction"] = hi

            repaired_steps.append(step)

        plan["planned_steps"] = repaired_steps
        plan["blocking_missing_information"] = self._collect_blockers(repaired_steps)
        plan["execution_state_repair"] = {
            "status": "repaired" if any(repair_notes.values()) else "unchanged",
            "runtime_context_used": bool(runtime_context),
            "notes": repair_notes,
        }
        return plan

    def _load_config(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _missing_names(self, missing_required: Any) -> list[str]:
        if isinstance(missing_required, list):
            return [str(x) for x in missing_required if str(x).strip()]
        if isinstance(missing_required, dict):
            return [str(k) for k in missing_required.keys() if str(k).strip()]
        return []

    def _missing_value(self, missing_required: Any, name: str) -> Any:
        if isinstance(missing_required, dict):
            return deepcopy(missing_required.get(name))
        return None

    def _is_optional_refinement(self, field_name: str) -> bool:
        normalized = field_name.strip().lower()
        if normalized in self.optional_refinement_fields:
            return True
        return normalized.endswith("_preference") or normalized.endswith("_preferences") or normalized.endswith("_style")

    def _can_mark_ready(self, step: dict[str, Any]) -> bool:
        if bool(step.get("requires_human_confirmation")) and self._requires_confirmation_by_structure(step):
            return False
        if self._requires_confirmation_by_structure(step):
            return False
        required_capability = step.get("required_capability")
        if isinstance(required_capability, dict):
            status = str(required_capability.get("status") or "").lower()
            if status in {"blocked", "unavailable", "missing"}:
                return False
        return True

    def _requires_confirmation_by_structure(self, step: dict[str, Any]) -> bool:
        # Do not treat orchestration fields such as next_action="execute" as
        # user-facing side effects. Confirmation is based on the step's target
        # operation and strategy, not the orchestration verb used to advance it.
        operation_text = " ".join(
            str(step.get(k, ""))
            for k in ["task_type", "action", "step_type", "objective"]
        ).lower()
        strategy_text = " ".join(str(x) for x in self._strategy_values(step)).lower()
        tokens = self._tokens(operation_text)
        strategy_tokens = self._tokens(strategy_text)
        strategy_is_read_only = bool(strategy_tokens.intersection(self.read_only_strategy_hints))
        has_irreversible = bool(tokens.intersection(self.irreversible_action_hints))
        has_read_only = bool(tokens.intersection(self.read_only_action_hints)) or strategy_is_read_only
        return has_irreversible and not has_read_only

    def _strategy_values(self, step: dict[str, Any]) -> list[str]:
        raw = step.get("execution_strategy")
        if isinstance(raw, list):
            return [str(x) for x in raw]
        if isinstance(raw, str):
            return [raw]
        return []

    def _human_interaction_only_optional(self, fields: Any) -> bool:
        if isinstance(fields, dict):
            names = [str(k) for k in fields.keys()]
        elif isinstance(fields, list):
            names = [str(x) for x in fields]
        else:
            return False
        return bool(names) and all(self._is_optional_refinement(name) for name in names)

    def _collect_blockers(self, steps: list[dict[str, Any]]) -> dict[str, list[str]]:
        blockers: dict[str, list[str]] = {}
        for step in steps:
            missing = step.get("missing_fields") if isinstance(step.get("missing_fields"), list) else []
            if missing:
                task_id = str(step.get("task_id") or step.get("step_id") or "unknown_task")
                blockers[task_id] = list(dict.fromkeys(str(x) for x in missing))
        return blockers

    def _tokens(self, value: str) -> set[str]:
        chars = [ch if ch.isalnum() else " " for ch in value]
        return {token for token in "".join(chars).split() if token}
