from __future__ import annotations

import json
import textwrap
from datetime import datetime, timezone
from typing import Any


class RuntimeBlueprintArtifactGenerator:
    """Convert a runtime capability blueprint into a sandboxable artifact plan.

    The generator is contract-driven and neutral. It does not know concrete
    business logic. If the blueprint already contains implementation files from
    the runtime planner, those files are passed through. Otherwise it creates a
    deterministic neutral callable that exposes declared schemas and refuses
    live side effects until runtime-generated implementation content exists.
    """

    REQUIRED_FIELDS = [
        "template_id",
        "entrypoint",
        "files",
        "input_schema",
        "output_schema",
        "verification_input",
        "verification_expectations",
    ]

    def materialize(self, blueprint: dict[str, Any], *, identity_contract: dict[str, Any] | None = None) -> dict[str, Any]:
        if not isinstance(blueprint, dict):
            blueprint = {}
        identity_contract = identity_contract or {}
        tool_id = str(
            blueprint.get("capability_id")
            or blueprint.get("tool_id")
            or blueprint.get("template_id")
            or identity_contract.get("requested_capability_id")
            or "generated_capability"
        ).strip()
        tool_id = self._safe_name(tool_id)
        entrypoint = blueprint.get("entrypoint") if isinstance(blueprint.get("entrypoint"), dict) else {"module": "tool.py", "function": "run"}
        entrypoint.setdefault("module", "tool.py")
        entrypoint.setdefault("function", "run")
        files = blueprint.get("files") if isinstance(blueprint.get("files"), list) else []
        if not self._valid_files(files):
            files = self._neutral_files(tool_id=tool_id, entrypoint=entrypoint)
        template = {
            "template_id": tool_id,
            "description": str(blueprint.get("description") or "Runtime-generated capability artifact."),
            "capabilities": blueprint.get("capabilities") if isinstance(blueprint.get("capabilities"), list) else [tool_id],
            "match_terms": blueprint.get("match_terms") if isinstance(blueprint.get("match_terms"), list) else [],
            "required_terms": blueprint.get("required_terms") if isinstance(blueprint.get("required_terms"), list) else [],
            "entrypoint": entrypoint,
            "files": files,
            "input_schema": self._schema_or_default(blueprint.get("input_schema"), "input"),
            "output_schema": self._schema_or_default(blueprint.get("output_schema"), "output"),
            "connection_schema": blueprint.get("connection_schema") if isinstance(blueprint.get("connection_schema"), dict) else {"type": "object", "additionalProperties": True},
            "secret_schema": blueprint.get("secret_schema") if isinstance(blueprint.get("secret_schema"), dict) else {"type": "object", "additionalProperties": True},
            "approval_policy": blueprint.get("approval_policy") if isinstance(blueprint.get("approval_policy"), dict) else {"mode": "required_for_side_effects"},
            "runtime_interface": blueprint.get("runtime_interface") if isinstance(blueprint.get("runtime_interface"), dict) else {"input_mode": "json", "output_mode": "json"},
            "runtime_execution_policy": blueprint.get("runtime_execution_policy") if isinstance(blueprint.get("runtime_execution_policy"), dict) else {"side_effects": "runtime_declared"},
            "verification_input": blueprint.get("verification_input") if isinstance(blueprint.get("verification_input"), dict) else {"_runtime": {"dry_run": True}},
            "verification_expectations": blueprint.get("verification_expectations") if isinstance(blueprint.get("verification_expectations"), dict) else {"status": "completed"},
            "acquisition_policy": blueprint.get("acquisition_policy") if isinstance(blueprint.get("acquisition_policy"), dict) else {"allow_policy_backed_basic_acquisition_without_external_evidence": True},
            "capability_match_contract": blueprint.get("capability_match_contract") if isinstance(blueprint.get("capability_match_contract"), dict) else {
                "expected_tool_id": tool_id,
                "expected_template_id": tool_id,
                "required_artifact_dir_name": tool_id,
                "required_markers": [tool_id],
                "forbidden_markers": [],
            },
            "blueprint_source": blueprint.get("blueprint_source") or "runtime_blueprint_planner",
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        return template

    def _valid_files(self, files: list[Any]) -> bool:
        return bool(files) and all(isinstance(item, dict) and str(item.get("path") or "").strip() and isinstance(item.get("content"), str) for item in files)

    def _schema_or_default(self, value: Any, name: str) -> dict[str, Any]:
        if isinstance(value, dict) and value:
            return value
        if name == "output":
            return {"type": "object", "properties": {"status": {"type": "string"}, "data": {"type": "object"}}, "additionalProperties": True}
        return {"type": "object", "additionalProperties": True}

    def _neutral_files(self, *, tool_id: str, entrypoint: dict[str, Any]) -> list[dict[str, str]]:
        module = str(entrypoint.get("module") or "tool.py")
        function = str(entrypoint.get("function") or "run")
        code = f'''from __future__ import annotations

from typing import Any

TOOL_ID = {tool_id!r}


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().casefold()
    if text in {{"true", "1", "yes", "y", "on"}}:
        return True
    if text in {{"false", "0", "no", "n", "off"}}:
        return False
    return default


def {function}(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {{}}
    runtime = payload.get("_runtime") if isinstance(payload.get("_runtime"), dict) else {{}}
    dry_run = _to_bool(payload.get("dry_run", runtime.get("dry_run", True)), default=True)
    return {{
        "status": "completed" if dry_run else "requires_runtime_implementation",
        "tool_id": TOOL_ID,
        "data": {{"dry_run": dry_run, "accepted_keys": sorted([str(k) for k in payload.keys()])}},
        "message": "Runtime blueprint artifact verified. Live behavior must be supplied by generated implementation content.",
        "provenance": {{"source": "runtime_blueprint_artifact", "side_effects": False}},
    }}
'''
        test = f'''from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[2] / "tools" / {tool_id!r}
SPEC = importlib.util.spec_from_file_location("generated_tool_under_test", ROOT / {module!r})
mod = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(mod)


def test_generated_tool_dry_run_contract():
    result = getattr(mod, {function!r})({{"_runtime": {{"dry_run": True}}}})
    assert result["status"] == "completed"
    assert result["tool_id"] == {tool_id!r}
'''
        return [
            {"path": module, "content": code},
            {"path": f"test_{tool_id}.py", "content": test},
        ]

    def _safe_name(self, value: str) -> str:
        return "".join(c if c.isalnum() else "_" for c in str(value)).strip("_").lower() or "generated_capability"
