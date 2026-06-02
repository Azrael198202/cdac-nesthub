from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ai_core.config.paths import PROJECT_ROOT, RUNTIME_GENERATED, RUNTIME_REGISTRY
from ai_core.runtime.capability.acquisition_gate import RuntimeCapabilityAcquisitionGate
from ai_core.runtime.capability.runtime_capability_template_store import RuntimeCapabilityTemplateStore
from ai_core.runtime.self_repair.engine import RuntimeSelfRepairEngine
from ai_core.runtime.observability.runtime_console import emit_console_event


@dataclass(frozen=True)
class TemplateMatch:
    template: dict[str, Any]
    score: int


class RuntimeCapabilityGapImplementer:
    """Generic runtime capability implementation lifecycle.

    ai_core stays generic: it does not contain concrete capability code.
    It loads runtime capability templates from configuration, resolves declared
    dependencies, writes artifacts under runtime/generated, validates them in a
    sandbox-like subprocess, verifies the registered callable, and registers only
    after validation succeeds.
    """

    def __init__(self, *, template_path: Path | None = None) -> None:
        self.template_path = template_path
        self.template_store = RuntimeCapabilityTemplateStore(explicit_path=template_path)
        self.generated_dir = RUNTIME_GENERATED / "tools"
        self.generated_tests_dir = RUNTIME_GENERATED / "tests"
        self.registry_path = RUNTIME_REGISTRY / "tool_registry.json"
        self.module_registry_path = RUNTIME_REGISTRY / "module_registry.json"
        self.acquisition_gate = RuntimeCapabilityAcquisitionGate()
        self.self_repair = RuntimeSelfRepairEngine(storage_root=RUNTIME_GENERATED / "self_repair")

    def implement_if_requested(
        self,
        *,
        user_input: str,
        evidence: dict[str, Any],
        run_id: str,
        allow_implementation: bool,
    ) -> dict[str, Any]:
        """Run the runtime capability acquisition pipeline.

        Pipeline contract:
        CapabilityAcquisitionRouter -> CapabilityIdentityExtractor ->
        TemplateResolver -> LLMCapabilityPlanner -> WebEvidenceRetriever
        gate -> ArtifactGenerator -> SandboxValidator -> CapabilityMatchContract
        -> RegistryWriter.

        The method is deliberately generic.  It never contains concrete
        capability behavior; behavior must come from a runtime template or a
        runtime-configured planner artifact.
        """
        pipeline: list[dict[str, Any]] = []

        stage_order = [
            "CapabilityAcquisitionRouter",
            "CapabilityIdentityExtractor",
            "TemplateResolver",
            "BlueprintPlanner",
            "ArtifactGenerator",
            "TemplateMaterializer",
            "WebEvidenceRetriever",
            "DependencyResolver",
            "AcquisitionGate",
            "CapabilityMatchContract",
            "SandboxValidator",
            "VerificationRun",
            "RegistrationGate",
            "RegistryWriter",
            "FinalSynthesis",
        ]
        stage_index_map = {name: idx + 1 for idx, name in enumerate(stage_order)}

        def mark(stage: str, status: str, **data: Any) -> None:
            event_payload = {"stage": stage, "status": status, **data}
            pipeline.append(event_payload)
            try:
                clean_data = {k: v for k, v in data.items() if k not in {"template"}}
                clean_data.update({
                    "run_id": run_id,
                    "stage_label": stage,
                    "stage_index": stage_index_map.get(stage),
                    "total_stages": len(stage_order),
                    "action": clean_data.get("action") or self._stage_action_text(stage, status, clean_data),
                    "console_message": self._stage_console_message(stage, status, clean_data),
                })
                emit_console_event(
                    area="capability_acquisition",
                    event=stage,
                    status=status,
                    message=str(clean_data.get("console_message") or f"{stage}: {status}"),
                    data=clean_data,
                )
            except Exception:
                pass

        mark("CapabilityAcquisitionRouter", "accepted" if allow_implementation else "not_requested")
        if not allow_implementation:
            return {"status": "not_requested", "reason": "implementation_was_not_requested", "pipeline": pipeline}

        identity_contract = self._extract_requested_identity_contract(user_input)
        mark("CapabilityIdentityExtractor", "completed", identity=identity_contract)

        urls = evidence.get("urls") if isinstance(evidence.get("urls"), list) else []
        templates = self._load_templates()
        match = self._select_template(str(user_input or ""), templates)
        template_source = "template_first"
        planner_record: dict[str, Any] | None = None
        if match:
            template = self._merge_identity_contract_into_template(match.template, identity_contract)
            mark("TemplateResolver", "matched", template_id=template.get("template_id"), score=match.score)
        else:
            mark("TemplateResolver", "template_not_found", template_locations=[str(p) for p in self.template_store.candidate_paths()])
            planner_record = self._plan_capability_with_runtime_planner(user_input=user_input, identity_contract=identity_contract, evidence=evidence)
            mark("BlueprintPlanner", str(planner_record.get("status") or "planner_failed"), planner=planner_record)
            if planner_record.get("status") != "planned" or not isinstance(planner_record.get("blueprint"), dict):
                repair = self._runtime_self_repair(
                    run_id=run_id,
                    stage="BlueprintPlanner",
                    status=str(planner_record.get("status") or "planner_failed"),
                    reason=str(planner_record.get("reason") or "planner_did_not_return_blueprint"),
                    payload={"identity": identity_contract, "planner": planner_record},
                    expected={"required_status": "planned", "required_payload": "blueprint"},
                )
                mark("RuntimeSelfRepairEngine", str(repair.get("status") or "repair_checked"), repair=repair)
                return {
                    "status": str(planner_record.get("status") or "planner_failed"),
                    "reason": str(planner_record.get("reason") or "template_not_found_and_blueprint_planner_failed"),
                    "requested_identity_contract": identity_contract,
                    "pipeline": pipeline,
                    "self_repair": repair,
                    "evidence_present": bool(urls),
                    "diagnosis": "blueprint_planner_failed_after_verified_evidence" if urls else "blueprint_planner_failed_before_verified_evidence",
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
            generated_template = self._artifact_template_from_blueprint(blueprint=dict(planner_record["blueprint"]), identity_contract=identity_contract, run_id=run_id)
            materialization = self._validate_runtime_template_shape(generated_template)
            mark("ArtifactGenerator", "blueprint_materialized" if materialization.get("passed") else "blueprint_materialization_failed", result=materialization)
            if not materialization.get("passed"):
                repair = self._runtime_self_repair(
                    run_id=run_id, stage="ArtifactGenerator", status="blueprint_materialization_failed",
                    reason="blueprint_could_not_be_materialized_to_runtime_template",
                    payload={"blueprint": planner_record.get("blueprint"), "validation": materialization},
                    expected={"template_shape_passed": True},
                )
                mark("RuntimeSelfRepairEngine", str(repair.get("status") or "repair_checked"), repair=repair)
                return {"status": "blueprint_materialization_failed", "pipeline": pipeline, "self_repair": repair, "generated_at": datetime.now(timezone.utc).isoformat()}
            template = self._merge_identity_contract_into_template(generated_template, identity_contract)
            persisted_template = self._persist_runtime_planned_template(template=template, run_id=run_id, planner_record=planner_record)
            mark("TemplateMaterializer", "completed" if persisted_template.get("passed") else "failed", result=persisted_template)
            template_source = "blueprint_planner_artifact_generator"
            match = TemplateMatch(template=template, score=int(float(planner_record.get("confidence_score") or 1) * 100))

        acquisition_policy = template.get("acquisition_policy") if isinstance(template.get("acquisition_policy"), dict) else {}
        planner_unknown = bool(planner_record and planner_record.get("needs_external_evidence"))
        allow_policy_backed_basic = bool(acquisition_policy.get("allow_policy_backed_basic_acquisition_without_external_evidence"))
        if not urls and planner_unknown:
            mark("WebEvidenceRetriever", "evidence_missing", reason="planner_requested_external_evidence")
        elif urls:
            mark("WebEvidenceRetriever", "completed", source_count=len(urls))
        else:
            mark("WebEvidenceRetriever", "not_required", policy_backed=allow_policy_backed_basic)

        if not urls and not allow_policy_backed_basic:
            repair = self._runtime_self_repair(
                run_id=run_id,
                stage="WebEvidenceRetriever",
                status="evidence_missing",
                reason="verified_evidence_required_before_implementation",
                payload={"identity": identity_contract, "template_id": template.get("template_id")},
                expected={"required_evidence": True},
            )
            mark("RuntimeSelfRepairEngine", str(repair.get("status") or "repair_checked"), repair=repair)
            return {
                "status": "evidence_missing",
                "reason": "verified_evidence_required_before_implementation",
                "template_id": template.get("template_id"),
                "requested_identity_contract": identity_contract,
                "pipeline": pipeline,
                "self_repair": repair,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        if not urls and allow_policy_backed_basic:
            evidence = dict(evidence)
            evidence["urls"] = ["runtime-policy://basic-generated-capability-contract"]
            evidence["source_note"] = "Policy-backed runtime acquisition without external source material."

        dependency_resolution = self._resolve_dependencies(template)
        mark("DependencyResolver", "completed" if dependency_resolution.get("passed") else str(dependency_resolution.get("status") or "failed"), result=dependency_resolution)
        if not dependency_resolution.get("passed"):
            repair = self._runtime_self_repair(
                run_id=run_id,
                stage="DependencyResolver",
                status=str(dependency_resolution.get("status") or "failed"),
                reason="dependency_resolution_failed",
                payload=dependency_resolution,
                expected={"passed": True},
            )
            mark("RuntimeSelfRepairEngine", str(repair.get("status") or "repair_checked"), repair=repair)
            return {
                "status": "dependency_resolution_failed",
                "template_id": template.get("template_id"),
                "score": match.score if match else 0,
                "dependency_resolution": dependency_resolution,
                "pipeline": pipeline,
                "self_repair": repair,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }

        artifact = self._write_artifact(template=template, run_id=run_id, evidence=evidence, dependency_resolution=dependency_resolution)
        mark("ArtifactGenerator", "completed", artifact=artifact)

        pre_gate = self.acquisition_gate.evaluate_before_validation(
            requested_capability=str(template.get("template_id") or ""),
            user_input=user_input,
            template=template,
            artifact=artifact,
            dependency_resolution=dependency_resolution,
        )
        self.acquisition_gate.write_report(artifact_dir=artifact.get("tool_dir"), report={"pre_validation": pre_gate})
        mark("AcquisitionGate", "passed" if pre_gate.get("passed") else str(pre_gate.get("status") or "failed"), result=pre_gate)

        capability_match = self._verify_capability_match(template=template, artifact=artifact, user_input=user_input)
        mark("CapabilityMatchContract", "completed" if capability_match.get("passed") else "identity_mismatch", result=capability_match)
        if not pre_gate.get("passed") or not capability_match.get("passed"):
            repair = self._runtime_self_repair(
                run_id=run_id,
                stage="CapabilityMatchContract",
                status="identity_mismatch",
                reason="generated_but_capability_mismatch",
                payload={"gate": pre_gate, "capability_match": capability_match, "artifact": artifact},
                expected={"capability_match_passed": True},
            )
            mark("RuntimeSelfRepairEngine", str(repair.get("status") or "repair_checked"), repair=repair)
            return {
                "status": "generated_but_capability_mismatch",
                "template_id": template.get("template_id"),
                "template_source": template_source,
                "score": match.score if match else 0,
                "requested_identity_contract": identity_contract,
                "dependency_resolution": dependency_resolution,
                "artifact": artifact,
                "capability_match": capability_match,
                "acquisition_gate": pre_gate,
                "validation": None,
                "verification_run": None,
                "registration": None,
                "pipeline": pipeline,
                "self_repair": repair,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }

        mark("SandboxValidator", "running", tool_id=artifact.get("tool_id"), tool_dir=artifact.get("tool_dir"), action="Preparing validation cases", console_message="Sandbox validation started")
        validation = self._validate_artifact(artifact, progress=mark)
        mark("SandboxValidator", "completed" if validation.get("passed") else "sandbox_failed", result=validation, action="Sandbox validation completed")
        verification_run: dict[str, Any] | None = None
        if validation.get("passed"):
            mark("VerificationRun", "running", tool_id=artifact.get("tool_id"), action="Executing generated capability with verification input", console_message="Verification run started")
            verification_run = self._execute_verification_run(template=template, artifact=artifact)
            mark("VerificationRun", "completed" if verification_run.get("passed") else "failed", result=verification_run, action="Verification run completed")

        registration_gate = self.acquisition_gate.evaluate_before_registration(
            pre_validation_decision=pre_gate,
            validation=validation,
            verification_run=verification_run or {},
        )
        self.acquisition_gate.write_report(artifact_dir=artifact.get("tool_dir"), report={"pre_validation": pre_gate, "registration": registration_gate})
        mark("RegistrationGate", "safe_to_register" if registration_gate.get("safe_to_register") else str(registration_gate.get("status") or "blocked"), result=registration_gate)

        registration: dict[str, Any] | None = None
        if registration_gate.get("safe_to_register"):
            registration = self._register_artifact(
                template=template,
                artifact=artifact,
                validation=validation,
                verification_run=verification_run or {},
                dependency_resolution=dependency_resolution,
                evidence=evidence,
                acquisition_gate=registration_gate,
            )
            mark("RegistryWriter", "completed", registration=registration)
            status = "implemented_tested_registered"
            repair = None
        else:
            failure_status = "sandbox_failed" if not validation.get("passed") else str(registration_gate.get("status") or "registration_blocked")
            repair = self._runtime_self_repair(
                run_id=run_id,
                stage="SandboxValidator" if not validation.get("passed") else "RegistrationGate",
                status=failure_status,
                reason=str(registration_gate.get("reason") or failure_status),
                payload={"validation": validation, "verification_run": verification_run, "registration_gate": registration_gate},
                expected={"safe_to_register": True},
            )
            mark("RuntimeSelfRepairEngine", str(repair.get("status") or "repair_checked"), repair=repair)
            status = str(registration_gate.get("status") or "generated_but_validation_failed")

        return {
            "status": status,
            "template_id": template.get("template_id"),
            "template_source": template_source,
            "requested_identity_contract": identity_contract,
            "score": match.score if match else 0,
            "dependency_resolution": dependency_resolution,
            "artifact": artifact,
            "capability_match": capability_match,
            "acquisition_gate": registration_gate,
            "validation": validation,
            "verification_run": verification_run,
            "registration": registration,
            "pipeline": pipeline,
            "self_repair": repair,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _load_templates(self) -> list[dict[str, Any]]:
        """Load runtime capability templates from runtime-owned storage.

        Concrete templates are no longer expected to live permanently under
        configs/.  This keeps ai_core generic while still allowing runtime
        acquired or seeded capability templates to be discovered.
        """
        return self.template_store.load_templates()


    def _extract_requested_identity_contract(self, user_input: str) -> dict[str, Any]:
        """Extract capability identity requirements declared by the user prompt.

        This stays generic: it looks for explicit identity language and simple
        capability names in the request. Domain-specific markers such as host
        names should be declared in the runtime template contract, not hardcoded
        in ai_core.
        """
        text = str(user_input or "")
        folded = text.casefold()
        requested_id = ""
        patterns = [
            r"capability\s+id\s+must\s+be\s*[:：]?\s*([a-zA-Z0-9_\-]+)",
            r"capability_id\s*[:=]\s*([a-zA-Z0-9_\-]+)",
            r"runtime\s+capability\s+registered\s+as\s+([a-zA-Z0-9_\-]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                requested_id = self._safe_name(match.group(1))
                break
        if not requested_id:
            # Generic slug fallback for common "Acquire runtime capability: X" form.
            title_match = re.search(r"Acquire\s+runtime\s+capability\s*:\s*\n?\s*([^\n.]+)", text, flags=re.IGNORECASE)
            if title_match:
                title = title_match.group(1).strip()
                if title:
                    requested_id = self._safe_name(title)
        forbidden_ids: list[str] = []
        for match in re.finditer(r"Do\s+not\s+(?:reuse|overwrite|register\s+this\s+capability\s+as)\s+([a-zA-Z0-9_\-]+)", text, flags=re.IGNORECASE):
            value = self._safe_name(match.group(1))
            if value and value not in forbidden_ids:
                forbidden_ids.append(value)
        return {
            "requested_capability_id": requested_id,
            "forbidden_capability_ids": forbidden_ids,
            "explicit": bool(requested_id or forbidden_ids),
            "raw_request_excerpt": text[:1000],
        }

    def _merge_identity_contract_into_template(self, template: dict[str, Any], identity_contract: dict[str, Any]) -> dict[str, Any]:
        if not identity_contract.get("explicit"):
            return template
        merged = dict(template)
        contract = dict(merged.get("capability_match_contract") if isinstance(merged.get("capability_match_contract"), dict) else {})
        requested_id = str(identity_contract.get("requested_capability_id") or "").strip()
        if requested_id:
            merged["template_id"] = requested_id
            contract["expected_tool_id"] = requested_id
            contract["expected_template_id"] = requested_id
            contract["required_artifact_dir_name"] = requested_id
        forbidden_ids = identity_contract.get("forbidden_capability_ids") if isinstance(identity_contract.get("forbidden_capability_ids"), list) else []
        if forbidden_ids:
            existing = contract.get("forbidden_tool_ids") if isinstance(contract.get("forbidden_tool_ids"), list) else []
            contract["forbidden_tool_ids"] = list(dict.fromkeys([*existing, *[str(x) for x in forbidden_ids if str(x)]]))
        merged["capability_match_contract"] = contract
        return merged


    def _plan_capability_with_runtime_planner(
        self,
        *,
        user_input: str,
        identity_contract: dict[str, Any],
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        """Invoke a runtime-configured planner hook for blueprint-only planning."""
        hook = os.environ.get("AI_CORE_CAPABILITY_PLANNER", "").strip()
        planner_origin = "env_hook" if hook else "runtime_generated_default_planner"
        try:
            if hook:
                module_name, function_name = hook.split(":", 1)
                module = __import__(module_name, fromlist=[function_name])
                planner = getattr(module, function_name)
            else:
                planner = self._load_runtime_generated_default_planner()
            if not callable(planner):
                raise TypeError("planner_hook_not_callable")
            payload = planner({
                "user_input": user_input,
                "identity_contract": identity_contract,
                "evidence": evidence,
                "required_blueprint_contract": self._runtime_planner_blueprint_contract(),
                "planner_origin": planner_origin,
            })
            if not isinstance(payload, dict):
                return {"status": "planner_failed", "reason": "planner_returned_non_object", "confidence_score": 0, "needs_external_evidence": True}
            if isinstance(payload.get("template"), dict) and not isinstance(payload.get("blueprint"), dict):
                return {"status": "planner_failed", "reason": "planner_returned_template_instead_of_blueprint", "confidence_score": float(payload.get("confidence_score") or 0), "needs_external_evidence": True}
            blueprint = payload.get("blueprint")
            confidence = float(payload.get("confidence_score") or payload.get("confidence") or 0)
            validation = self._validate_runtime_blueprint_shape(blueprint if isinstance(blueprint, dict) else {})
            if not validation.get("passed"):
                return {"status": "planner_failed", "reason": "planner_blueprint_contract_failed", "confidence_score": confidence, "needs_external_evidence": True, "validation": validation, "raw": payload}
            fallback_used = bool(payload.get("fallback_used")) or str(payload.get("planner_engine") or "") == "deterministic_blueprint_fallback"
            min_confidence = float(os.environ.get("AI_CORE_CAPABILITY_PLANNER_MIN_CONFIDENCE", "0.70") or 0.70)
            if confidence < min_confidence and not fallback_used:
                return {
                    "status": "planner_low_confidence",
                    "reason": "planner_confidence_below_threshold",
                    "confidence_score": confidence,
                    "needs_external_evidence": True,
                    "blueprint": blueprint,
                    "validation": validation,
                    "planner_origin": planner_origin,
                    "planner_engine": payload.get("planner_engine"),
                    "model": payload.get("model"),
                    "model_source": payload.get("model_source"),
                }
            return {
                "status": "planned",
                "confidence_score": confidence,
                "needs_external_evidence": bool(payload.get("needs_external_evidence")),
                "blueprint": blueprint,
                "validation": validation,
                "planner_origin": planner_origin,
                "planner_engine": payload.get("planner_engine"),
                "model": payload.get("model"),
                "model_source": payload.get("model_source"),
                "fallback_used": fallback_used,
                "fallback_reason": payload.get("fallback_reason"),
                "model_planner_attempt": payload.get("model_planner_attempt"),
            }
        except ValueError:
            return {"status": "planner_failed", "reason": "planner_hook_must_use_module_colon_function_format", "confidence_score": 0, "needs_external_evidence": True, "planner_origin": planner_origin}
        except Exception as exc:
            return {"status": "planner_failed", "reason": f"{exc.__class__.__name__}: {str(exc)[:500]}", "confidence_score": 0, "needs_external_evidence": True}


    def _runtime_planner_blueprint_contract(self) -> dict[str, Any]:
        return {
            "required_fields": ["capability_category", "requires_connection", "requires_secret", "required_inputs"],
            "optional_fields": ["required_connection_fields", "required_secret_fields", "approval_mode", "execution_mode", "verification_mode"],
            "planner_rule": "Return blueprint JSON only. Do not generate code, schemas, policies, registry entries, or concrete runtime values.",
            "artifact_boundary": "ArtifactGenerator materializes runtime artifacts under runtime/generated; registry writes only after validation.",
        }

    def _validate_runtime_blueprint_shape(self, blueprint: dict[str, Any]) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        checks.append({"name": "blueprint_is_object", "passed": isinstance(blueprint, dict)})
        checks.append({"name": "capability_category", "passed": bool(str(blueprint.get("capability_category") or "").strip())})
        checks.append({"name": "requires_connection_boolean", "passed": isinstance(blueprint.get("requires_connection"), bool)})
        checks.append({"name": "requires_secret_boolean", "passed": isinstance(blueprint.get("requires_secret"), bool)})
        checks.append({"name": "required_inputs_list", "passed": isinstance(blueprint.get("required_inputs"), list)})
        passed = all(bool(item.get("passed")) for item in checks)
        return {"passed": passed, "status": "completed" if passed else "failed", "checks": checks}

    def _artifact_template_from_blueprint(self, *, blueprint: dict[str, Any], identity_contract: dict[str, Any], run_id: str) -> dict[str, Any]:
        capability_id = str(identity_contract.get("requested_capability_id") or "runtime_generated_adapter").strip() or "runtime_generated_adapter"
        safe_id = self._safe_name(capability_id)
        required_inputs = [self._safe_field_name(x) for x in blueprint.get("required_inputs", []) if self._safe_field_name(x)]
        connection_fields = [self._safe_field_name(x) for x in blueprint.get("required_connection_fields", []) if self._safe_field_name(x)]
        secret_fields = [self._safe_field_name(x) for x in blueprint.get("required_secret_fields", []) if self._safe_field_name(x)]
        if bool(blueprint.get("requires_connection")) and not connection_fields:
            connection_fields = ["endpoint"]
        if bool(blueprint.get("requires_secret")) and not secret_fields:
            secret_fields = ["credential"]
        input_schema = self._object_schema(required_inputs)
        connection_schema = self._object_schema(connection_fields)
        secret_schema = self._object_schema(secret_fields)
        tool_code = self._generic_adapter_tool_code(safe_id=safe_id)
        test_code = self._generic_adapter_test_code(safe_id=safe_id)
        return {
            "template_id": safe_id,
            "description": "Runtime-generated generic adapter materialized from a compact blueprint.",
            "capabilities": [str(blueprint.get("capability_category") or "adapter")],
            "match_terms": [safe_id],
            "entrypoint": {"module": "tool.py", "function": "run"},
            "files": [{"path": "tool.py", "content": tool_code}, {"path": "test_tool.py", "content": test_code}],
            "input_schema": input_schema,
            "output_schema": {"type": "object", "properties": {"status": {"type": "string"}, "data": {"type": "object"}, "provenance": {"type": "object"}}, "required": ["status", "data", "provenance"]},
            "connection_schema": connection_schema,
            "secret_schema": secret_schema,
            "approval_policy": {"mode": str(blueprint.get("approval_mode") or "always"), "reason": "Runtime-generated adapters require explicit operator approval unless runtime policy overrides it."},
            "runtime_interface": {"input_style": "json", "configuration_sources": ["input", "connection", "secrets", "_runtime"]},
            "runtime_execution_policy": {"execution_mode": str(blueprint.get("execution_mode") or "adapter"), "no_hardcoded_runtime_values": True},
            "verification_input": {"input_data": {name: "test" for name in required_inputs}, "connection": {name: "test" for name in connection_fields}, "secrets": {name: "test" for name in secret_fields}, "dry_run": True},
            "verification_expectations": {"status_in": ["dry_run", "completed"], "must_return_provenance": True},
            "acquisition_policy": {"allow_policy_backed_basic_acquisition_without_external_evidence": True},
            "capability_match_contract": {"expected_tool_id": safe_id, "expected_template_id": safe_id, "required_artifact_dir_name": safe_id, "forbidden_markers": ["password =", "token =", "api_key ="]},
            "blueprint": blueprint,
            "run_id": run_id,
        }

    def _object_schema(self, fields: list[str]) -> dict[str, Any]:
        return {"type": "object", "properties": {name: {"type": "string"} for name in fields}, "required": fields}

    def _safe_field_name(self, value: Any) -> str:
        name = re.sub(r"[^a-zA-Z0-9_]+", "_", str(value or "").strip()).strip("_").lower()
        if not name:
            return ""
        if name[0].isdigit():
            name = "field_" + name
        return name[:64]

    def _generic_adapter_tool_code(self, *, safe_id: str) -> str:
        lines = [
            "from __future__ import annotations",
            "from datetime import datetime, timezone",
            "from typing import Any",
            f"TOOL_ID = {safe_id!r}",
            "",
            "def _runtime_section(payload: dict[str, Any], key: str) -> dict[str, Any]:",
            "    runtime = payload.get('_runtime') if isinstance(payload.get('_runtime'), dict) else {}",
            "    value = payload.get(key) if isinstance(payload.get(key), dict) else runtime.get(key)",
            "    return value if isinstance(value, dict) else {}",
            "",
            "def run(payload: dict[str, Any] | None = None) -> dict[str, Any]:",
            "    payload = payload if isinstance(payload, dict) else {}",
            "    input_data = payload.get('input_data') if isinstance(payload.get('input_data'), dict) else {k: v for k, v in payload.items() if not str(k).startswith('_')}",
            "    connection = _runtime_section(payload, 'connection')",
            "    secrets = _runtime_section(payload, 'secrets')",
            "    dry_run = str(payload.get('dry_run', payload.get('test_mode', True))).casefold() not in {'false', '0', 'no', 'off'}",
            "    missing_inputs = [k for k, v in input_data.items() if v in (None, '')]",
            "    if missing_inputs:",
            "        return {'status': 'missing_input', 'data': {'missing': missing_inputs}, 'provenance': {'tool_id': TOOL_ID, 'executed_at': datetime.now(timezone.utc).isoformat(), 'dry_run': dry_run}}",
            "    return {'status': 'dry_run' if dry_run else 'completed', 'data': {'accepted_input_keys': sorted(input_data.keys()), 'connection_configured': bool(connection), 'secret_configured': bool(secrets)}, 'provenance': {'tool_id': TOOL_ID, 'executed_at': datetime.now(timezone.utc).isoformat(), 'dry_run': dry_run}}",
        ]
        return "\n".join(lines) + "\n"

    def _generic_adapter_test_code(self, *, safe_id: str) -> str:
        lines = [
            "from tool import run",
            "",
            "def test_run_dry_mode():",
            "    result = run({'input_data': {'field_1': 'value'}, 'dry_run': True})",
            "    assert result['status'] in {'dry_run', 'completed'}",
            f"    assert result['provenance']['tool_id'] == {safe_id!r}",
        ]
        return "\n".join(lines) + "\n"


    def _load_runtime_generated_default_planner(self) -> Callable[[dict[str, Any]], dict[str, Any]]:
        """Load the runtime-owned default planner when no env hook is set.

        The core only loads a neutral callable contract from runtime/generated.
        Concrete capability knowledge belongs to runtime-generated artifacts or packaged
        runtime assets, not to ai_core. If both are absent, the planner fails
        explicitly so self-repair can report the missing boundary asset.
        """
        candidates = [
            RUNTIME_GENERATED / "capability_planners" / "default_capability_planner.py",
            RUNTIME_GENERATED / "capability_planners" / "evidence_template_planner.py",
            PROJECT_ROOT / "runtime_assets" / "seeds" / "capability_planners" / "default_capability_planner.py",
        ]
        for path in candidates:
            if path.exists():
                return self._load_function(path, "plan")
        raise RuntimeError("runtime_generated_default_capability_planner_missing")


    def _persist_runtime_planned_template(self, *, template: dict[str, Any], run_id: str, planner_record: dict[str, Any]) -> dict[str, Any]:
        """Persist a planned template into runtime/generated for future Template First use.

        This is the materialization boundary: a planner output becomes a
        runtime-owned template only after it satisfies the neutral template
        contract.  ai_core does not contain the concrete template content.
        """
        validation = self._validate_runtime_template_shape(template)
        if not validation.get("passed"):
            return {"passed": False, "status": "failed", "reason": "template_contract_failed", "validation": validation}
        template_dir = RUNTIME_GENERATED / "capability_templates"
        template_dir.mkdir(parents=True, exist_ok=True)
        path = template_dir / "runtime_planned_capability_templates.json"
        try:
            existing = json.loads(path.read_text(encoding="utf-8") or "{}") if path.exists() else {}
        except json.JSONDecodeError:
            existing = {}
        if not isinstance(existing, dict):
            existing = {}
        templates = existing.get("templates") if isinstance(existing.get("templates"), list) else []
        template_id = str(template.get("template_id") or "generated_capability")
        kept = [item for item in templates if not (isinstance(item, dict) and str(item.get("template_id") or "") == template_id)]
        kept.append(template)
        payload = {
            "version": "1.0",
            "source": "runtime_capability_planner",
            "last_run_id": run_id,
            "planner_status": planner_record.get("status"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "templates": kept,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"passed": True, "status": "completed", "path": str(path), "template_id": template_id, "validation": validation}

    def _runtime_planner_template_contract(self) -> dict[str, Any]:
        return {
            "required_top_level_fields": ["template_id", "entrypoint", "files", "input_schema", "output_schema", "verification_input", "verification_expectations"],
            "required_entrypoint_fields": ["module", "function"],
            "required_contract_fields": ["expected_tool_id", "required_artifact_dir_name", "required_markers", "forbidden_markers"],
            "storage_boundary": "runtime/generated for artifacts; runtime/registry for registrations; configs only for policy and model routing",
        }

    def _validate_runtime_template_shape(self, template: dict[str, Any]) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        required = self._runtime_planner_template_contract()["required_top_level_fields"]
        for key in required:
            ok = key in template and template.get(key) not in (None, "", [], {})
            checks.append({"name": f"field:{key}", "passed": ok})
        entrypoint = template.get("entrypoint") if isinstance(template.get("entrypoint"), dict) else {}
        for key in self._runtime_planner_template_contract()["required_entrypoint_fields"]:
            ok = bool(str(entrypoint.get(key) or "").strip())
            checks.append({"name": f"entrypoint:{key}", "passed": ok})
        files = template.get("files") if isinstance(template.get("files"), list) else []
        files_ok = bool(files) and all(isinstance(item, dict) and str(item.get("path") or "").strip() and isinstance(item.get("content"), str) for item in files)
        checks.append({"name": "files_have_paths_and_content", "passed": files_ok})
        passed = all(bool(item.get("passed")) for item in checks)
        return {"passed": passed, "status": "completed" if passed else "failed", "checks": checks}

    def _runtime_self_repair(
        self,
        *,
        run_id: str,
        stage: str,
        status: str,
        reason: str,
        payload: dict[str, Any],
        expected: dict[str, Any],
    ) -> dict[str, Any]:
        report = {
            "run_id": run_id,
            "node_id": "capability_acquisition_pipeline",
            "stage": stage,
            "status": status,
            "reason": reason,
            "payload": payload,
            "expected_contract": expected,
            "runtime_state": {"pipeline": "capability_acquisition"},
        }
        diagnosis = self.self_repair.diagnose(report)
        plan = self.self_repair.plan(report)
        trace_dir = RUNTIME_GENERATED / "self_repair" / "capability_acquisition"
        trace_path = self.self_repair.write_trace(result=plan, trace_dir=trace_dir, name=f"{run_id}_{self._safe_name(stage)}")
        return {"status": plan.status, "diagnosis": diagnosis, "plan": plan.to_dict(), "trace_path": str(trace_path)}

    def _select_template(self, user_input: str, templates: list[dict[str, Any]]) -> TemplateMatch | None:
        value = " " + user_input.casefold() + " "
        best: TemplateMatch | None = None
        for template in templates:
            terms = template.get("match_terms") if isinstance(template.get("match_terms"), list) else []
            required = template.get("required_terms") if isinstance(template.get("required_terms"), list) else []
            if required and not all(str(term).casefold() in value for term in required):
                continue
            term_score = sum(1 for term in terms if str(term).casefold() in value)
            generic_required_terms = {"capability", "runtime", "tool", "action"}
            if term_score <= 0 and required and all(str(term).casefold() in generic_required_terms for term in required):
                continue
            score = term_score
            # Template selection remains contract-driven.  A template may declare
            # a numeric priority to prefer a precise capability template over a
            # broader fallback template when both match the same request.
            try:
                score += int(template.get("selection_priority") or 0)
            except Exception:
                pass
            if required:
                score += len(required) * 10
            if score <= 0:
                continue
            candidate = TemplateMatch(template=template, score=score)
            if best is None or candidate.score > best.score:
                best = candidate
        return best

    def _resolve_dependencies(self, template: dict[str, Any]) -> dict[str, Any]:
        dependencies = template.get("dependencies") if isinstance(template.get("dependencies"), list) else []
        checks: list[dict[str, Any]] = []
        if not dependencies:
            return {"passed": True, "status": "not_required", "checks": checks}
        for item in dependencies:
            if not isinstance(item, dict):
                continue
            import_name = str(item.get("import_name") or item.get("module") or "").strip()
            package_name = str(item.get("package") or item.get("name") or import_name).strip()
            auto_install = bool(item.get("auto_install", True))
            check = {"package": package_name, "import_name": import_name, "auto_install": auto_install}
            if import_name and self._module_available(import_name):
                check.update({"status": "available", "installed": False})
                checks.append(check)
                continue
            if not package_name or not auto_install:
                check.update({"status": "missing", "installed": False})
                checks.append(check)
                return {"passed": False, "status": "missing_dependency", "checks": checks}
            pip_proc = self._pip_install(package_name)
            check.update({
                "status": "installed" if pip_proc.get("returncode") == 0 else "install_failed",
                "installed": pip_proc.get("returncode") == 0,
                "pip": pip_proc,
            })
            if pip_proc.get("returncode") != 0:
                checks.append(check)
                return {"passed": False, "status": "dependency_installation_failed", "checks": checks}
            if import_name and not self._module_available(import_name):
                check["status"] = "install_completed_but_import_failed"
                checks.append(check)
                return {"passed": False, "status": "dependency_import_verification_failed", "checks": checks}
            checks.append(check)
        return {"passed": True, "status": "completed", "checks": checks}

    def _module_available(self, name: str) -> bool:
        try:
            return importlib.util.find_spec(name) is not None
        except Exception:
            return False

    def _clean_subprocess_env(self, *, pythonpath: str | None = None) -> dict[str, str]:
        """Return a stable validation environment for generated artifacts.

        VS Code/debugpy and similar launchers can inject PYTHONPATH, pydevd,
        or debugger bootstrap variables into child Python processes.  Generated
        capability validation must be isolated from the IDE runtime; otherwise
        a valid generated tool may fail before its own code is even compiled.
        """
        blocked_prefixes = ("PYDEVD", "DEBUGPY", "VSCODE", "PYCHARM")
        blocked_names = {
            "PYTHONPATH",
            "PYTHONHOME",
            "PYTHONSTARTUP",
            "PYTHONBREAKPOINT",
            "PYDEVD_LOAD_VALUES_ASYNC",
        }
        clean: dict[str, str] = {}
        for key, value in os.environ.items():
            upper = key.upper()
            if upper in blocked_names or any(upper.startswith(prefix) for prefix in blocked_prefixes):
                continue
            clean[key] = value
        if pythonpath:
            clean["PYTHONPATH"] = pythonpath
        clean.setdefault("PYTHONNOUSERSITE", "1")
        clean.setdefault("PYTHONDONTWRITEBYTECODE", "1")
        return clean

    def _python_executable_candidates(self) -> list[str]:
        """Return Python executables suitable for sandbox validation.

        The active process may be launched under an IDE/debugger wrapper.  For
        generated capability validation we prefer the base interpreter and fall
        back to common launcher names.  Duplicates are removed while preserving
        order.
        """
        candidates: list[str] = []
        base_executable = getattr(sys, "_base_executable", None)
        for item in [base_executable, sys.executable, "python3"]:
            value = str(item or "").strip()
            if value and value not in candidates:
                candidates.append(value)
        return candidates

    def _run_isolated_python(self, args: list[str], *, cwd: Path, timeout: int = 15, pythonpath: str | None = None) -> dict[str, Any]:
        """Run a generated-artifact validation command with debugger isolation.

        A failure caused by debugger bootstrap, not by generated code, should
        not be treated as a capability validation failure until every candidate
        interpreter has been tried.  The returned payload keeps every attempt so
        the devil-checker can distinguish a real implementation failure from an
        environment failure.
        """
        attempts: list[dict[str, Any]] = []
        for exe in self._python_executable_candidates():
            try:
                proc = subprocess.run(
                    [exe, "-I", *args],
                    cwd=str(cwd),
                    env=self._clean_subprocess_env(pythonpath=pythonpath),
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=timeout,
                )
                attempt = {
                    "executable": exe,
                    "returncode": proc.returncode,
                    "stdout": proc.stdout[-2000:],
                    "stderr": proc.stderr[-2000:],
                }
                attempts.append(attempt)
                if proc.returncode == 0:
                    return {**attempt, "attempts": attempts}
                stderr_l = (proc.stderr or "").casefold()
                environment_failure = any(
                    marker in stderr_l
                    for marker in ["debugpy", "pydevd", "keyboardinterrupt", "_bz2", "pythonhome", "pythonpath"]
                )
                if not environment_failure:
                    return {**attempt, "attempts": attempts}
            except Exception as exc:
                attempts.append({"executable": exe, "returncode": -1, "stdout": "", "stderr": f"{exc.__class__.__name__}: {exc}"})
                continue
        last = attempts[-1] if attempts else {"executable": "", "returncode": -1, "stdout": "", "stderr": "no_python_executable_available"}
        return {**last, "attempts": attempts}

    def _pip_install(self, package_name: str) -> dict[str, Any]:
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pip", "install", package_name],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=120,
            )
            return {"returncode": proc.returncode, "stdout": proc.stdout[-3000:], "stderr": proc.stderr[-3000:]}
        except Exception as exc:
            return {"returncode": 1, "error_type": exc.__class__.__name__, "stderr": str(exc)[:2000], "stdout": ""}

    def _write_artifact(
        self,
        *,
        template: dict[str, Any],
        run_id: str,
        evidence: dict[str, Any],
        dependency_resolution: dict[str, Any],
    ) -> dict[str, Any]:
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
            "dependencies": template.get("dependencies") if isinstance(template.get("dependencies"), list) else [],
            "dependency_resolution": dependency_resolution,
            "input_schema": template.get("input_schema") if isinstance(template.get("input_schema"), dict) else {},
            "output_schema": template.get("output_schema") if isinstance(template.get("output_schema"), dict) else {},
            "connection_schema": template.get("connection_schema") if isinstance(template.get("connection_schema"), dict) else {},
            "secret_schema": template.get("secret_schema") if isinstance(template.get("secret_schema"), dict) else {},
            "approval_policy": template.get("approval_policy") if isinstance(template.get("approval_policy"), dict) else {},
            "runtime_interface": template.get("runtime_interface") if isinstance(template.get("runtime_interface"), dict) else {},
            "verification_input": template.get("verification_input") if isinstance(template.get("verification_input"), dict) else {},
            "written_files": written,
            "test_dir": str(tests_dir),
            "test_files": test_files,
        }
        manifest_path = tool_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"tool_id": safe_id, "tool_dir": str(tool_dir), "test_dir": str(tests_dir), "manifest_path": str(manifest_path), "written_files": written, "test_files": test_files}


    def _verify_capability_match(self, *, template: dict[str, Any], artifact: dict[str, Any], user_input: str) -> dict[str, Any]:
        """Verify that the generated artifact really implements the matched capability.

        This is intentionally contract-driven. ai_core does not know concrete
        capability domains. A runtime template may declare
        marker strings that must appear in generated files/schemas before the
        artifact is allowed to proceed to sandbox validation and registration.
        """
        contract = template.get("capability_match_contract") if isinstance(template.get("capability_match_contract"), dict) else {}
        if not contract:
            return {"passed": True, "status": "not_required", "checks": []}
        tool_dir = Path(str(artifact.get("tool_dir") or ""))
        checks: list[dict[str, Any]] = []
        combined_parts: list[str] = [str(template.get("template_id") or ""), str(template.get("description") or ""), user_input or ""]
        if tool_dir.exists():
            for path in sorted(tool_dir.rglob("*")):
                if path.name in {"capability_match_report.json", "acquisition_gate_report.json", "verification_report.json", "test_report.json"}:
                    continue
                if path.is_file() and path.suffix.lower() in {".py", ".json", ".md", ".txt", ".yaml", ".yml"}:
                    try:
                        text = path.read_text(encoding="utf-8", errors="ignore")
                        if path.name == "manifest.json":
                            try:
                                payload = json.loads(text or "{}")
                                if isinstance(payload, dict):
                                    payload.pop("capability_match_contract", None)
                                    text = json.dumps(payload, ensure_ascii=False)
                            except Exception:
                                pass
                        combined_parts.append(text)
                    except Exception:
                        continue
        combined = "\n".join(combined_parts).casefold()
        required_markers = contract.get("required_markers") if isinstance(contract.get("required_markers"), list) else []
        forbidden_markers = contract.get("forbidden_markers") if isinstance(contract.get("forbidden_markers"), list) else []
        missing = [str(marker) for marker in required_markers if str(marker).casefold() not in combined]
        present_forbidden = [str(marker) for marker in forbidden_markers if str(marker).casefold() in combined]
        checks.append({"name": "required_markers", "passed": not missing, "missing": missing})
        checks.append({"name": "forbidden_markers", "passed": not present_forbidden, "present": present_forbidden})
        expected_tool_id = str(contract.get("expected_tool_id") or "").strip()
        actual_tool_id = str(artifact.get("tool_id") or template.get("template_id") or "").strip()
        expected_template_id = str(contract.get("expected_template_id") or "").strip()
        actual_template_id = str(template.get("template_id") or "").strip()
        required_dir_name = str(contract.get("required_artifact_dir_name") or "").strip()
        actual_dir_name = Path(str(artifact.get("tool_dir") or "")).name if artifact.get("tool_dir") else ""
        forbidden_tool_ids = [str(x).strip() for x in contract.get("forbidden_tool_ids", []) if str(x).strip()] if isinstance(contract.get("forbidden_tool_ids"), list) else []
        id_checks_passed = True
        if expected_tool_id:
            ok = actual_tool_id == expected_tool_id
            id_checks_passed = id_checks_passed and ok
            checks.append({"name": "expected_tool_id", "passed": ok, "expected": expected_tool_id, "actual": actual_tool_id})
        if expected_template_id:
            ok = actual_template_id == expected_template_id
            id_checks_passed = id_checks_passed and ok
            checks.append({"name": "expected_template_id", "passed": ok, "expected": expected_template_id, "actual": actual_template_id})
        if required_dir_name:
            ok = actual_dir_name == required_dir_name
            id_checks_passed = id_checks_passed and ok
            checks.append({"name": "required_artifact_dir_name", "passed": ok, "expected": required_dir_name, "actual": actual_dir_name})
        if forbidden_tool_ids:
            present_ids = [x for x in forbidden_tool_ids if x in {actual_tool_id, actual_template_id, actual_dir_name}]
            ok = not present_ids
            id_checks_passed = id_checks_passed and ok
            checks.append({"name": "forbidden_tool_ids", "passed": ok, "present": present_ids})
        passed = not missing and not present_forbidden and id_checks_passed
        report = {
            "passed": passed,
            "status": "completed" if passed else "failed",
            "checks": checks,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if tool_dir.exists():
            (tool_dir / "capability_match_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    def _stage_action_text(self, stage: str, status: str, data: dict[str, Any]) -> str:
        if stage == "TemplateResolver":
            return "Resolving runtime template" if status != "template_not_found" else "No template found; switching to blueprint planner"
        if stage == "BlueprintPlanner":
            source = data.get("source") or (data.get("planner") if isinstance(data.get("planner"), str) else "runtime planner")
            return f"Planning compact blueprint through {source}"
        if stage == "ArtifactGenerator":
            return "Materializing runtime artifact from blueprint/template"
        if stage == "SandboxValidator":
            return str(data.get("action") or "Running sandbox validation")
        if stage == "VerificationRun":
            return str(data.get("action") or "Executing verification run")
        if stage == "RegistryWriter":
            return "Writing registry entry"
        return str(data.get("action") or f"{stage} {status}")

    def _stage_console_message(self, stage: str, status: str, data: dict[str, Any]) -> str:
        if stage == "TemplateResolver" and status == "template_not_found":
            return "Template not found; BlueprintPlanner will be used"
        if stage == "BlueprintPlanner" and status == "planned":
            planner = data.get("planner") if isinstance(data.get("planner"), dict) else {}
            origin = planner.get("planner_origin") or planner.get("planner_engine") or data.get("source") or "planner"
            return f"Blueprint generated by {origin}"
        if stage == "ArtifactGenerator" and status in {"blueprint_materialized", "completed"}:
            src = data.get("template_source") or data.get("source") or "runtime plan"
            return f"Artifact generated from {src}"
        if stage == "DependencyResolver" and status == "completed":
            return "Dependency resolution completed"
        if stage == "SandboxValidator" and status == "running":
            return str(data.get("console_message") or "Sandbox validation started")
        if stage == "SandboxValidator" and status == "completed":
            return "Sandbox validation completed"
        if stage == "VerificationRun" and status == "running":
            return "Verification run started"
        if stage == "VerificationRun" and status == "completed":
            return "Verification run completed"
        return str(data.get("console_message") or f"{stage}: {status}")

    def _validate_artifact(self, artifact: dict[str, Any], progress: Callable[..., None] | None = None) -> dict[str, Any]:
        tool_dir = Path(str(artifact.get("tool_dir") or ""))
        if not tool_dir.exists():
            return {"passed": False, "status": "failed", "reason": "artifact_directory_missing"}
        checks: list[dict[str, Any]] = []
        py_files = [str(p) for p in tool_dir.rglob("*.py")]
        if py_files:
            if progress:
                progress("SandboxValidator", "running", action="Compiling generated Python files", console_message="Validation case 1 running: python compile")
            proc = self._run_isolated_python(["-m", "py_compile", *py_files], cwd=tool_dir, timeout=15)
            checks.append({
                "name": "python_compile",
                "returncode": proc.get("returncode"),
                "stdout": str(proc.get("stdout") or "")[-2000:],
                "stderr": str(proc.get("stderr") or "")[-2000:],
                "attempts": proc.get("attempts", []),
            })
            if proc.get("returncode") != 0:
                if progress:
                    progress("SandboxValidator", "failed", action="Python compile failed", console_message="Validation case 1 failed: python compile")
                return {"passed": False, "status": "failed", "checks": checks}
            if progress:
                progress("SandboxValidator", "completed", action="Python compile passed; preparing unit tests", console_message="Validation case 1 passed: python compile")
        test_candidates: list[Path] = []
        test_dir = Path(str(artifact.get("test_dir") or ""))
        if test_dir.exists():
            test_candidates.extend(sorted(test_dir.glob("test_*.py")))
        legacy_test_file = tool_dir / "test_tool.py"
        if legacy_test_file.exists() and legacy_test_file not in test_candidates:
            test_candidates.append(legacy_test_file)
        for case_index, test_file in enumerate(test_candidates, start=2):
            if progress:
                progress("SandboxValidator", "running", action=f"Executing validation case {case_index}: {test_file.name}", console_message=f"Validation case {case_index} running: {test_file.name}")
            runner = (
                "import runpy, sys; "
                f"sys.path.insert(0, {json.dumps(str(tool_dir))}); "
                f"runpy.run_path({json.dumps(str(test_file))}, run_name='__main__')"
            )
            proc = self._run_isolated_python(["-c", runner], cwd=tool_dir, timeout=15)
            check = {
                "name": "unit_test",
                "test_file": str(test_file),
                "returncode": proc.get("returncode"),
                "stdout": str(proc.get("stdout") or "")[-2000:],
                "stderr": str(proc.get("stderr") or "")[-2000:],
                "attempts": proc.get("attempts", []),
            }
            checks.append(check)
            self._write_test_report(artifact, check)
            if proc.get("returncode") != 0:
                if progress:
                    progress("SandboxValidator", "failed", action=f"Validation case {case_index} failed", console_message=f"Validation case {case_index} failed: {test_file.name}")
                return {"passed": False, "status": "failed", "checks": checks}
            if progress:
                progress("SandboxValidator", "completed", action=f"Validation case {case_index} passed", console_message=f"Validation case {case_index} passed: {test_file.name}")
        return {"passed": True, "status": "completed", "checks": checks}

    def _execute_verification_run(self, *, template: dict[str, Any], artifact: dict[str, Any]) -> dict[str, Any]:
        entrypoint = template.get("entrypoint") if isinstance(template.get("entrypoint"), dict) else {}
        module_path = Path(str(artifact.get("tool_dir") or "")) / str(entrypoint.get("module") or "tool.py")
        function_name = str(entrypoint.get("function") or "run")
        verification_input = template.get("verification_input") if isinstance(template.get("verification_input"), dict) else {}
        if not module_path.exists():
            return {"passed": False, "status": "failed", "reason": "implementation_module_missing"}
        try:
            fn = self._load_function(module_path, function_name)
            output = fn(dict(verification_input))
            expectations = template.get("verification_expectations") if isinstance(template.get("verification_expectations"), dict) else {}
            passed = self._matches_expectations(output, expectations)
            report = {
                "passed": passed,
                "status": "completed" if passed else "failed",
                "input": verification_input,
                "output": output,
                "expectations": expectations,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            self._write_verification_report(artifact, report)
            return report
        except Exception as exc:
            report = {"passed": False, "status": "failed", "error_type": exc.__class__.__name__, "error": str(exc)[:2000]}
            self._write_verification_report(artifact, report)
            return report

    def _load_function(self, path: Path, function_name: str) -> Callable[[dict[str, Any]], Any]:
        module_name = f"runtime_generated_{path.stem}_{abs(hash(str(path)))}"
        spec = importlib.util.spec_from_file_location(module_name, str(path))
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Unable to load module spec: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fn = getattr(module, function_name, None)
        if not callable(fn):
            raise RuntimeError(f"Callable '{function_name}' not found in {path}")
        return fn

    def _matches_expectations(self, output: Any, expectations: dict[str, Any]) -> bool:
        if not expectations:
            return isinstance(output, dict) and str(output.get("status") or "").lower() in {"completed", "success", "ok", "executed", ""}
        if not isinstance(output, dict):
            return False
        status_in = expectations.get("status_in") if isinstance(expectations.get("status_in"), list) else None
        if status_in is not None and str(output.get("status") or "") not in {str(x) for x in status_in}:
            return False
        if bool(expectations.get("must_return_provenance")) and not isinstance(output.get("provenance"), dict):
            return False
        for key, expected in expectations.items():
            if key in {"status_in", "must_return_provenance"}:
                continue
            actual = output.get(key)
            if actual != expected:
                data = output.get("data") if isinstance(output.get("data"), dict) else {}
                if data.get(key) != expected:
                    return False
        return True

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

    def _write_verification_report(self, artifact: dict[str, Any], report: dict[str, Any]) -> None:
        tool_dir = Path(str(artifact.get("tool_dir") or ""))
        if tool_dir.exists():
            (tool_dir / "verification_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        test_dir = Path(str(artifact.get("test_dir") or ""))
        if test_dir.exists():
            (test_dir / "verification_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def _register_artifact(
        self,
        *,
        template: dict[str, Any],
        artifact: dict[str, Any],
        validation: dict[str, Any],
        verification_run: dict[str, Any],
        dependency_resolution: dict[str, Any],
        evidence: dict[str, Any],
        acquisition_gate: dict[str, Any] | None = None,
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
            "dependencies": template.get("dependencies") if isinstance(template.get("dependencies"), list) else [],
            "dependency_resolution": dependency_resolution,
            "input_schema": template.get("input_schema") if isinstance(template.get("input_schema"), dict) else {},
            "output_schema": template.get("output_schema") if isinstance(template.get("output_schema"), dict) else {},
            "connection_schema": template.get("connection_schema") if isinstance(template.get("connection_schema"), dict) else {},
            "secret_schema": template.get("secret_schema") if isinstance(template.get("secret_schema"), dict) else {},
            "approval_policy": template.get("approval_policy") if isinstance(template.get("approval_policy"), dict) else {},
            "runtime_interface": template.get("runtime_interface") if isinstance(template.get("runtime_interface"), dict) else {},
            "runtime_execution_policy": template.get("runtime_execution_policy") if isinstance(template.get("runtime_execution_policy"), dict) else {},
            "verification": {
                "sandbox_verification": bool(validation.get("passed")),
                "execution_verification": bool(verification_run.get("passed")),
                "registration_gate": acquisition_gate or {},
                "checks": validation.get("checks", []),
                "verification_run": verification_run,
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
            "input_schema": tool_record.get("input_schema", {}),
            "output_schema": tool_record.get("output_schema", {}),
            "connection_schema": tool_record.get("connection_schema", {}),
            "secret_schema": tool_record.get("secret_schema", {}),
            "approval_policy": tool_record.get("approval_policy", {}),
            "runtime_interface": tool_record.get("runtime_interface", {}),
            "runtime_execution_policy": tool_record.get("runtime_execution_policy", {}),
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
