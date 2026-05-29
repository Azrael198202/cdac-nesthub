from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_core.config.paths import CONFIGS_DIR, RUNTIME_GENERATED, RUNTIME_REGISTRY


@dataclass(frozen=True)
class TemplateMatch:
    template: dict[str, Any]
    score: int


class RuntimeCapabilityGapImplementer:
    """Generic runtime capability implementation lifecycle.

    ai_core stays generic: this class does not contain concrete capability code.
    It loads runtime capability templates from configuration, writes the chosen
    artifact under runtime/generated, validates it in an isolated subprocess,
    and registers it only after validation succeeds.
    """

    def __init__(self, *, template_path: Path | None = None) -> None:
        self.template_path = template_path or (CONFIGS_DIR / "runtime_capability_templates.json")
        self.generated_dir = RUNTIME_GENERATED / "tools"
        self.generated_tests_dir = RUNTIME_GENERATED / "tests"
        self.registry_path = RUNTIME_REGISTRY / "tool_registry.json"
        self.module_registry_path = RUNTIME_REGISTRY / "module_registry.json"

    def implement_if_requested(
        self,
        *,
        user_input: str,
        evidence: dict[str, Any],
        run_id: str,
        allow_implementation: bool,
    ) -> dict[str, Any]:
        if not allow_implementation:
            return {"status": "not_requested", "reason": "implementation_was_not_requested"}
        urls = evidence.get("urls") if isinstance(evidence.get("urls"), list) else []
        if not urls:
            return {"status": "blocked", "reason": "verified_evidence_required_before_implementation"}
        templates = self._load_templates()
        match = self._select_template(str(user_input or ""), templates)
        if not match:
            return {
                "status": "blocked",
                "reason": "no_runtime_template_matched_requested_capability",
                "template_path": str(self.template_path),
            }
        template = match.template
        artifact = self._write_artifact(template=template, run_id=run_id, evidence=evidence)
        validation = self._validate_artifact(artifact)
        registration = None
        if validation.get("passed"):
            registration = self._register_artifact(template=template, artifact=artifact, validation=validation, evidence=evidence)
            status = "implemented_tested_registered"
        else:
            status = "generated_but_validation_failed"
        return {
            "status": status,
            "template_id": template.get("template_id"),
            "score": match.score,
            "artifact": artifact,
            "validation": validation,
            "registration": registration,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _load_templates(self) -> list[dict[str, Any]]:
        if not self.template_path.exists():
            return []
        try:
            data = json.loads(self.template_path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError:
            return []
        templates = data.get("templates") if isinstance(data, dict) else data
        return [x for x in templates if isinstance(x, dict)] if isinstance(templates, list) else []

    def _select_template(self, user_input: str, templates: list[dict[str, Any]]) -> TemplateMatch | None:
        value = " " + user_input.casefold() + " "
        best: TemplateMatch | None = None
        for template in templates:
            terms = template.get("match_terms") if isinstance(template.get("match_terms"), list) else []
            required = template.get("required_terms") if isinstance(template.get("required_terms"), list) else []
            if required and not all(str(term).casefold() in value for term in required):
                continue
            score = sum(1 for term in terms if str(term).casefold() in value)
            if score <= 0:
                continue
            candidate = TemplateMatch(template=template, score=score)
            if best is None or candidate.score > best.score:
                best = candidate
        return best

    def _write_artifact(self, *, template: dict[str, Any], run_id: str, evidence: dict[str, Any]) -> dict[str, Any]:
        safe_id = self._safe_name(str(template.get("template_id") or "generated_capability"))
        tool_dir = self.generated_dir / safe_id
        tool_dir.mkdir(parents=True, exist_ok=True)
        files = template.get("files") if isinstance(template.get("files"), list) else []
        written: list[str] = []
        for item in files:
            if not isinstance(item, dict):
                continue
            rel = self._safe_relative_path(str(item.get("path") or ""))
            if not rel:
                continue
            target = tool_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            content = str(item.get("content") or "")
            target.write_text(content, encoding="utf-8")
            written.append(str(target))
        tests_dir = self.generated_tests_dir / safe_id
        tests_dir.mkdir(parents=True, exist_ok=True)
        test_files: list[str] = []
        for written_path in written:
            source_path = Path(written_path)
            if source_path.name.startswith("test_") and source_path.suffix == ".py":
                target = tests_dir / source_path.name
                target.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")
                test_files.append(str(target))
        manifest = {
            "tool_id": safe_id,
            "template_id": template.get("template_id"),
            "capabilities": template.get("capabilities") if isinstance(template.get("capabilities"), list) else [],
            "source_urls": evidence.get("urls") if isinstance(evidence.get("urls"), list) else [],
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "entrypoint": template.get("entrypoint", {}),
            "written_files": written,
            "test_dir": str(tests_dir),
            "test_files": test_files,
        }
        manifest_path = tool_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"tool_id": safe_id, "tool_dir": str(tool_dir), "test_dir": str(tests_dir), "manifest_path": str(manifest_path), "written_files": written, "test_files": test_files}

    def _validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        tool_dir = Path(str(artifact.get("tool_dir") or ""))
        if not tool_dir.exists():
            return {"passed": False, "status": "failed", "reason": "artifact_directory_missing"}
        checks: list[dict[str, Any]] = []
        py_files = [str(p) for p in tool_dir.rglob("*.py")]
        if py_files:
            proc = subprocess.run(
                [sys.executable, "-m", "py_compile", *py_files],
                cwd=str(tool_dir),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=20,
            )
            checks.append({"name": "python_compile", "returncode": proc.returncode, "stdout": proc.stdout[-2000:], "stderr": proc.stderr[-2000:]})
            if proc.returncode != 0:
                return {"passed": False, "status": "failed", "checks": checks}
        test_candidates: list[Path] = []
        test_dir = Path(str(artifact.get("test_dir") or ""))
        if test_dir.exists():
            test_candidates.extend(sorted(test_dir.glob("test_*.py")))
        legacy_test_file = tool_dir / "test_tool.py"
        if legacy_test_file.exists() and legacy_test_file not in test_candidates:
            test_candidates.append(legacy_test_file)
        for test_file in test_candidates:
            proc = subprocess.run(
                [sys.executable, str(test_file)],
                cwd=str(tool_dir),
                env={**__import__("os").environ, "PYTHONPATH": str(tool_dir)},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=20,
            )
            check = {"name": "unit_test", "test_file": str(test_file), "returncode": proc.returncode, "stdout": proc.stdout[-2000:], "stderr": proc.stderr[-2000:]}
            checks.append(check)
            self._write_test_report(artifact, check)
            if proc.returncode != 0:
                return {"passed": False, "status": "failed", "checks": checks}
        return {"passed": True, "status": "completed", "checks": checks}


    def _write_test_report(self, artifact: dict[str, Any], check: dict[str, Any]) -> None:
        test_dir = Path(str(artifact.get("test_dir") or ""))
        if not test_dir.exists():
            return
        report_path = test_dir / "test_report.json"
        payload = {
            "tool_id": artifact.get("tool_id"),
            "status": "passed" if check.get("returncode") == 0 else "failed",
            "check": check,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _register_artifact(
        self,
        *,
        template: dict[str, Any],
        artifact: dict[str, Any],
        validation: dict[str, Any],
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        RUNTIME_REGISTRY.mkdir(parents=True, exist_ok=True)
        registry = self._load_registry(self.registry_path)
        module_registry = self._load_registry(self.module_registry_path)
        tool_id = str(artifact.get("tool_id") or template.get("template_id") or "generated_capability")
        entrypoint = template.get("entrypoint") if isinstance(template.get("entrypoint"), dict) else {}
        tool_record = {
            "tool_id": tool_id,
            "name": tool_id,
            "capability": (template.get("capabilities") or [tool_id])[0] if isinstance(template.get("capabilities"), list) and template.get("capabilities") else tool_id,
            "capabilities": template.get("capabilities") if isinstance(template.get("capabilities"), list) else [tool_id],
            "status": "enabled",
            "spec_path": str(Path(str(artifact.get("tool_dir"))) / "manifest.json"),
            "implementation": {
                "type": "python_module",
                "module_path": str(Path(str(artifact.get("tool_dir"))) / str(entrypoint.get("module") or "tool.py")),
                "function": str(entrypoint.get("function") or "run"),
            },
            "verification": {
                "sandbox_verification": bool(validation.get("passed")),
                "checks": validation.get("checks", []),
                "test_dir": artifact.get("test_dir"),
                "test_files": artifact.get("test_files", []),
            },
            "source_urls": evidence.get("urls") if isinstance(evidence.get("urls"), list) else [],
            "registered_at": datetime.now(timezone.utc).isoformat(),
        }
        module_record = {
            "module_id": tool_id,
            "name": tool_id,
            "status": "enabled",
            "source": "runtime_capability_gap_resolution",
            "runtime_generated": True,
            "module_path": tool_record["implementation"]["module_path"],
            "callable": tool_record["implementation"]["function"],
            "tool_id": tool_id,
            "capabilities": tool_record["capabilities"],
            "manifest_path": tool_record["spec_path"],
            "verification": tool_record["verification"],
            "registered_at": tool_record["registered_at"],
        }
        registry[tool_id] = tool_record
        module_registry[tool_id] = module_record
        self.registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
        self.module_registry_path.write_text(json.dumps(module_registry, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"status": "registered", "registry_path": str(self.registry_path), "module_registry_path": str(self.module_registry_path), "tool_record": tool_record, "module_record": module_record}

    def _load_registry(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _safe_name(self, value: str) -> str:
        return "".join(c if c.isalnum() else "_" for c in value).strip("_").lower() or "generated_capability"

    def _safe_relative_path(self, value: str) -> str:
        candidate = Path(value)
        if not value or candidate.is_absolute() or ".." in candidate.parts:
            return ""
        return str(candidate)
