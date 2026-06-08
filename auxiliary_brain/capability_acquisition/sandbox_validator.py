from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class RuntimeCapabilitySandboxValidator:
    """Static registration-quality validator for generated runtime artifacts.

    This file belongs to auxiliary_brain so ai_core stays free of concrete
    capability generation logic. The acquisition router uses equivalent checks
    inline for backward compatibility; this class documents and exposes the same
    policy for future composition.
    """

    def validate_registration_quality(self, artifact_dir: str | Path) -> dict[str, Any]:
        tool_dir = Path(artifact_dir)
        manifest_path = tool_dir / "manifest.json"
        checks: list[dict[str, Any]] = []
        if not manifest_path.exists():
            return {"passed": False, "status": "not_registered", "reason": "manifest_missing", "checks": checks}
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return {"passed": False, "status": "not_registered", "reason": f"manifest_unreadable:{exc.__class__.__name__}", "checks": checks}
        if str(manifest.get("artifact_kind") or "") == "blueprint_only_not_registerable":
            return {"passed": False, "status": "not_registered", "reason": "blueprint_artifact_is_not_registerable", "checks": checks}
        for name in ["input_schema", "connection_schema", "secret_schema"]:
            check = self._schema_is_specific(manifest.get(name) if isinstance(manifest.get(name), dict) else {})
            checks.append({"name": name, **check})
            if not check.get("passed"):
                return {"passed": False, "status": "not_registered", "reason": f"{name}_is_empty_or_open", "checks": checks}
        text = self._source_text(tool_dir).casefold()
        forbidden = ["requires_runtime_implementation", "runtime blueprint artifact verified", "blueprint only; not a registerable"]
        present = [item for item in forbidden if item in text]
        checks.append({"name": "no_stub_markers", "passed": not present, "present": present})
        if present:
            return {"passed": False, "status": "not_registered", "reason": "stub_markers_present", "checks": checks}
        policy = manifest.get("runtime_execution_policy") if isinstance(manifest.get("runtime_execution_policy"), dict) else {}
        verification = manifest.get("verification_input") if isinstance(manifest.get("verification_input"), dict) else {}
        runtime = verification.get("_runtime") if isinstance(verification.get("_runtime"), dict) else {}
        requires_sandbox_mode = str(policy.get("side_effects") or "").casefold() not in {"none", "pure", "read_only", "read-only"}
        has_sandbox_mode = bool(runtime.get("dry_run") is True or runtime.get("mock") is True or runtime.get("test_mode") is True)
        checks.append({"name": "sandbox_mode_declared_for_effectful_runtime", "passed": (not requires_sandbox_mode) or has_sandbox_mode, "requires_sandbox_mode": requires_sandbox_mode, "runtime": runtime})
        if requires_sandbox_mode and not has_sandbox_mode:
            return {"passed": False, "status": "not_registered", "reason": "sandbox_mode_missing_for_effectful_runtime", "checks": checks}
        return {"passed": True, "status": "registerable", "checks": checks}

    def _schema_is_specific(self, schema: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(schema, dict) or schema.get("type") != "object":
            return {"passed": False, "reason": "schema_is_not_object"}
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        if not properties:
            if schema.get("additionalProperties") is False and bool(schema.get("x-empty-schema-allowed")):
                return {"passed": True, "property_count": 0, "required": schema.get("required", []), "empty_schema_allowed": True}
            return {"passed": False, "reason": "schema_has_no_properties"}
        if schema.get("additionalProperties") is True and not schema.get("required"):
            return {"passed": False, "reason": "schema_is_too_open"}
        return {"passed": True, "property_count": len(properties), "required": schema.get("required", [])}

    def _source_text(self, tool_dir: Path) -> str:
        parts: list[str] = []
        for path in sorted(tool_dir.rglob("*")):
            if path.is_file() and path.suffix.lower() in {".py", ".json", ".md", ".txt", ".yaml", ".yml"}:
                try:
                    parts.append(path.read_text(encoding="utf-8", errors="ignore"))
                except Exception:
                    continue
        return "\n".join(parts)
