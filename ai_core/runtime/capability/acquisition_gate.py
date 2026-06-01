from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class AcquisitionGateDecision:
    """Domain-neutral decision for runtime-generated capability activation."""

    status: str
    safe_to_register: bool
    passed: bool
    stage: str
    checks: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RuntimeCapabilityAcquisitionGate:
    """Single registration gate for runtime-generated capabilities.

    ai_core remains generic: this gate does not know concrete tool domains. It
    only enforces contracts declared by runtime templates/artifacts:

    generated artifact -> dependency decision -> capability match contract ->
    sandbox/static validation -> verification execution -> registry enablement.

    Any generated tool, primitive tool, or autonomous capability acquisition can
    reuse this gate before a registry record is marked enabled.
    """

    ACCEPTED_ISOLATION_LEVELS = {"docker", "venv", "clean_subprocess", "isolated_subprocess", "local_clean_subprocess"}

    def evaluate_before_validation(
        self,
        *,
        requested_capability: str = "",
        user_input: str = "",
        template: dict[str, Any] | None = None,
        artifact: dict[str, Any] | None = None,
        dependency_resolution: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        dep = dependency_resolution if isinstance(dependency_resolution, dict) else {"passed": True, "status": "not_required"}
        dep_passed = bool(dep.get("passed", True))
        checks.append({"name": "dependency_resolution", "passed": dep_passed, "result": dep})
        if not dep_passed:
            return AcquisitionGateDecision(
                status="blocked_dependency_resolution_failed",
                safe_to_register=False,
                passed=False,
                stage="dependency_resolution",
                checks=checks,
                reason="Declared dependencies were not resolved successfully.",
            ).to_dict()

        match = self.verify_capability_match(
            requested_capability=requested_capability,
            user_input=user_input,
            template=template or {},
            artifact=artifact or {},
        )
        checks.append({"name": "capability_match_contract", "passed": bool(match.get("passed")), "result": match})
        if not match.get("passed"):
            return AcquisitionGateDecision(
                status="generated_but_capability_mismatch",
                safe_to_register=False,
                passed=False,
                stage="capability_match",
                checks=checks,
                reason="Generated artifact did not satisfy its declared capability match contract.",
            ).to_dict()

        return AcquisitionGateDecision(
            status="pre_validation_passed",
            safe_to_register=False,
            passed=True,
            stage="pre_validation",
            checks=checks,
            reason="Dependency and capability match checks passed; sandbox validation is still required.",
        ).to_dict()

    def evaluate_before_registration(
        self,
        *,
        pre_validation_decision: dict[str, Any] | None = None,
        validation: dict[str, Any] | None = None,
        verification_run: dict[str, Any] | None = None,
        sandbox_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        if isinstance(pre_validation_decision, dict):
            checks.append({"name": "pre_validation_gate", "passed": bool(pre_validation_decision.get("passed")), "result": pre_validation_decision})
            if not pre_validation_decision.get("passed"):
                return AcquisitionGateDecision(
                    status=str(pre_validation_decision.get("status") or "blocked_pre_validation_failed"),
                    safe_to_register=False,
                    passed=False,
                    stage="pre_validation",
                    checks=checks,
                    reason=str(pre_validation_decision.get("reason") or "Pre-validation gate failed."),
                ).to_dict()

        validation = validation if isinstance(validation, dict) else {}
        sandbox_result = sandbox_result if isinstance(sandbox_result, dict) else {}
        verification_run = verification_run if isinstance(verification_run, dict) else {}

        validation_passed = bool(validation.get("passed") or validation.get("safe_to_register") or sandbox_result.get("safe_to_register"))
        checks.append({"name": "sandbox_validation", "passed": validation_passed, "result": validation or sandbox_result})
        if not validation_passed:
            return AcquisitionGateDecision(
                status="generated_but_validation_failed",
                safe_to_register=False,
                passed=False,
                stage="sandbox_validation",
                checks=checks,
                reason=self._reason(validation or sandbox_result, "Sandbox validation did not pass."),
            ).to_dict()

        isolation = str(validation.get("isolation_level") or sandbox_result.get("mode") or validation.get("mode") or "").strip().lower()
        if isolation and isolation not in self.ACCEPTED_ISOLATION_LEVELS:
            checks.append({"name": "isolation_level", "passed": False, "isolation_level": isolation})
            return AcquisitionGateDecision(
                status="generated_but_isolation_level_untrusted",
                safe_to_register=False,
                passed=False,
                stage="sandbox_isolation",
                checks=checks,
                reason=f"Sandbox isolation level is not trusted for registry enablement: {isolation}",
            ).to_dict()
        checks.append({"name": "isolation_level", "passed": True, "isolation_level": isolation or "not_reported"})

        verification_passed = bool(verification_run.get("passed") or sandbox_result.get("safe_to_register"))
        checks.append({"name": "verification_run", "passed": verification_passed, "result": verification_run or sandbox_result})
        if not verification_passed:
            return AcquisitionGateDecision(
                status="generated_but_verification_failed",
                safe_to_register=False,
                passed=False,
                stage="verification_run",
                checks=checks,
                reason=self._reason(verification_run or sandbox_result, "Verification run did not pass."),
            ).to_dict()

        return AcquisitionGateDecision(
            status="registration_gate_passed",
            safe_to_register=True,
            passed=True,
            stage="registration_gate",
            checks=checks,
            reason="Capability artifact passed all registration gate checks.",
        ).to_dict()

    def verify_capability_match(
        self,
        *,
        requested_capability: str = "",
        user_input: str = "",
        template: dict[str, Any] | None = None,
        artifact: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        template = template if isinstance(template, dict) else {}
        artifact = artifact if isinstance(artifact, dict) else {}
        manifest = artifact.get("manifest") if isinstance(artifact.get("manifest"), dict) else {}
        contract = (
            template.get("capability_match_contract")
            if isinstance(template.get("capability_match_contract"), dict)
            else manifest.get("capability_match_contract")
            if isinstance(manifest.get("capability_match_contract"), dict)
            else artifact.get("capability_match_contract")
            if isinstance(artifact.get("capability_match_contract"), dict)
            else {}
        )
        if not contract:
            return {"passed": True, "status": "not_required", "checks": []}

        combined = self._artifact_text(artifact=artifact, template=template, user_input=user_input, requested_capability=requested_capability).casefold()
        required = [str(x) for x in contract.get("required_markers", []) if str(x)] if isinstance(contract.get("required_markers"), list) else []
        forbidden = [str(x) for x in contract.get("forbidden_markers", []) if str(x)] if isinstance(contract.get("forbidden_markers"), list) else []
        missing = [x for x in required if x.casefold() not in combined]
        present_forbidden = [x for x in forbidden if x.casefold() in combined]
        checks = [
            {"name": "required_markers", "passed": not missing, "missing": missing},
            {"name": "forbidden_markers", "passed": not present_forbidden, "present": present_forbidden},
        ]

        expected_tool_id = str(contract.get("expected_tool_id") or "").strip()
        expected_template_id = str(contract.get("expected_template_id") or "").strip()
        required_dir_name = str(contract.get("required_artifact_dir_name") or "").strip()
        artifact_tool_id = str(artifact.get("tool_id") or "").strip()
        template_id = str(template.get("template_id") or "").strip()
        artifact_dir_name = Path(str(artifact.get("tool_dir") or artifact.get("artifact_dir") or "")).name if (artifact.get("tool_dir") or artifact.get("artifact_dir")) else ""
        forbidden_tool_ids = [str(x).strip() for x in contract.get("forbidden_tool_ids", []) if str(x).strip()] if isinstance(contract.get("forbidden_tool_ids"), list) else []
        identity_passed = True
        if expected_tool_id:
            ok = artifact_tool_id == expected_tool_id
            identity_passed = identity_passed and ok
            checks.append({"name": "expected_tool_id", "passed": ok, "expected": expected_tool_id, "actual": artifact_tool_id})
        if expected_template_id:
            ok = template_id == expected_template_id
            identity_passed = identity_passed and ok
            checks.append({"name": "expected_template_id", "passed": ok, "expected": expected_template_id, "actual": template_id})
        if required_dir_name:
            ok = artifact_dir_name == required_dir_name
            identity_passed = identity_passed and ok
            checks.append({"name": "required_artifact_dir_name", "passed": ok, "expected": required_dir_name, "actual": artifact_dir_name})
        if forbidden_tool_ids:
            present_ids = [x for x in forbidden_tool_ids if x in {artifact_tool_id, template_id, artifact_dir_name}]
            ok = not present_ids
            identity_passed = identity_passed and ok
            checks.append({"name": "forbidden_tool_ids", "passed": ok, "present": present_ids})

        passed = not missing and not present_forbidden and identity_passed
        return {
            "passed": passed,
            "status": "completed" if passed else "failed",
            "checks": checks,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def write_report(self, *, artifact_dir: str | Path | None, report: dict[str, Any], filename: str = "acquisition_gate_report.json") -> None:
        if not artifact_dir:
            return
        path = Path(artifact_dir)
        try:
            path.mkdir(parents=True, exist_ok=True)
            (path / filename).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            return

    def _artifact_text(self, *, artifact: dict[str, Any], template: dict[str, Any], user_input: str, requested_capability: str) -> str:
        # Do not include the contract itself in the scanned text; otherwise a
        # forbidden marker declared by the contract would make every artifact
        # fail. Only implementation material, schemas, names, and descriptions
        # are checked.
        template_projection = {
            "template_id": template.get("template_id"),
            "description": template.get("description"),
            "capabilities": template.get("capabilities"),
            "entrypoint": template.get("entrypoint"),
        }
        parts: list[str] = [requested_capability, user_input, json.dumps(template_projection, ensure_ascii=False, default=str)]
        manifest = artifact.get("manifest") if isinstance(artifact.get("manifest"), dict) else {}
        if manifest:
            manifest_projection = {k: v for k, v in manifest.items() if k != "capability_match_contract"}
            parts.append(json.dumps(manifest_projection, ensure_ascii=False, default=str))
        files = artifact.get("files") if isinstance(artifact.get("files"), dict) else None
        if files:
            for name, content in files.items():
                parts.append(str(name))
                parts.append(str(content))
        for key in ("tool_dir", "artifact_dir"):
            raw = artifact.get(key)
            if not raw:
                continue
            root = Path(str(raw))
            if not root.exists():
                continue
            for path in sorted(root.rglob("*")):
                if path.name in {"capability_match_report.json", "acquisition_gate_report.json", "verification_report.json", "test_report.json"}:
                    continue
                if path.is_file() and path.suffix.lower() in {".py", ".json", ".md", ".txt", ".yaml", ".yml"}:
                    try:
                        parts.append(path.read_text(encoding="utf-8", errors="ignore"))
                    except Exception:
                        pass
        return "\n".join(parts)

    def _reason(self, result: dict[str, Any], fallback: str) -> str:
        for key in ("reason", "error", "message"):
            value = result.get(key)
            if value:
                return str(value)[:2000]
        return fallback
