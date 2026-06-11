from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TaskGraphCompileGate:
    profile_dir: Path = Path("runtime") / "prompt_profiles"
    registry_path: Path = Path("runtime") / "registry" / "tool_registry.json"

    def validate(self, compiled: dict[str, Any]) -> dict[str, Any]:
        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        steps = compiled.get("steps") if isinstance(compiled.get("steps"), list) else []
        step_ids = {str(step.get("step_id")) for step in steps if isinstance(step, dict)}
        for step in steps:
            if not isinstance(step, dict):
                continue
            sid = str(step.get("step_id") or "")
            profile = (step.get("prompt_profile") or {}).get("prompt_profile") if isinstance(step.get("prompt_profile"), dict) else ""
            if not profile:
                errors.append({"code": "prompt_profile_missing", "step_id": sid})
            elif not (self.profile_dir / f"{profile}.prompt").exists():
                errors.append({"code": "prompt_profile_not_found", "step_id": sid, "prompt_profile": profile})
            owner = (step.get("execution_contract") or {}).get("execution_owner") if isinstance(step.get("execution_contract"), dict) else ""
            if not str(owner or "").strip():
                errors.append({"code": "execution_owner_missing", "step_id": sid})
            source_contract = step.get("source_contract") if isinstance(step.get("source_contract"), dict) else {}
            order = source_contract.get("material_order") if isinstance(source_contract.get("material_order"), list) else []
            if "blocked" not in order:
                errors.append({"code": "source_contract_missing_blocked_terminal", "step_id": sid})
            capability_id = str((step.get("execution_contract") or {}).get("capability_id") or "").strip() if isinstance(step.get("execution_contract"), dict) else ""
            if capability_id and not self._capability_registered(capability_id):
                warnings.append({"code": "capability_not_registered_at_compile_time", "step_id": sid, "capability_id": capability_id})
        for binding in compiled.get("bindings") if isinstance(compiled.get("bindings"), list) else []:
            if not isinstance(binding, dict):
                continue
            missing = [key for key in ("binding_id", "source_step", "source_field", "target_step", "target_field") if not str(binding.get(key) or "").strip()]
            if missing:
                errors.append({"code": "binding_incomplete", "binding": binding, "missing": missing})
                continue
            if binding.get("source_step") not in step_ids:
                errors.append({"code": "binding_source_step_unknown", "binding_id": binding.get("binding_id"), "source_step": binding.get("source_step")})
            if binding.get("target_step") not in step_ids:
                errors.append({"code": "binding_target_step_unknown", "binding_id": binding.get("binding_id"), "target_step": binding.get("target_step")})
            if binding.get("template_parsing_enabled") is not False:
                errors.append({"code": "binding_template_parsing_not_disabled", "binding_id": binding.get("binding_id")})
        return {
            "gate": "TaskGraphCompileGate",
            "passed": not errors,
            "status": "passed" if not errors else "failed",
            "errors": errors,
            "warnings": warnings,
            "checked_items": {
                "step_count": len(steps),
                "binding_count": len(compiled.get("bindings") if isinstance(compiled.get("bindings"), list) else []),
            },
        }

    def _capability_registered(self, capability_id: str) -> bool:
        try:
            data = __import__('json').loads(self.registry_path.read_text(encoding='utf-8'))
        except Exception:
            return False
        text = __import__('json').dumps(data, ensure_ascii=False)
        return capability_id in text
