from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ai_core.config.paths import PROJECT_ROOT, RUNTIME_GENERATED, RUNTIME_REGISTRY
from auxiliary_brain.runtime.capability.acquisition_gate import RuntimeCapabilityAcquisitionGate
from auxiliary_brain.runtime.capability.runtime_capability_template_store import RuntimeCapabilityTemplateStore
from auxiliary_brain.runtime.self_repair.engine import RuntimeSelfRepairEngine
from auxiliary_brain.runtime.observability.runtime_console import emit_console_event
from ai_core.runtime.state import runtime_state_manager, capability_scoped_state_store
from auxiliary_brain.runtime.observability.stage_observer import RuntimeStageObserver
from auxiliary_brain.capability_acquisition.code_generator import RuntimeBlueprintArtifactGenerator
from auxiliary_brain.capability_acquisition.classification import CapabilityClassifier
from auxiliary_brain.capability_acquisition.trace_logger import CapabilityAcquisitionTraceLogger


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
        self.stage_observer = RuntimeStageObserver()
        self.blueprint_artifact_generator = RuntimeBlueprintArtifactGenerator()
        self.trace_logger = CapabilityAcquisitionTraceLogger()
        self.capability_classifier = CapabilityClassifier()

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

        def mark(stage: str, status: str, **data: Any) -> None:
            record = {"stage": stage, "status": status, **data}
            pipeline.append(record)
            try:
                self.trace_logger.record(run_id=run_id, stage=stage, status=status, payload=data)
            except Exception:
                pass
            try:
                emit_console_event(
                    area="capability_acquisition",
                    event=stage,
                    status=status,
                    message=f"{stage}: {status}",
                    data={k: v for k, v in data.items() if k not in {"template"}},
                )
            except Exception:
                pass
            try:
                stage_index = len(pipeline)
                progress_hint = min(95.0, max(1.0, stage_index * 5.0))
                normalized_status = str(status or "running")
                if normalized_status in {"accepted", "planned", "runtime_native", "safe_to_register", "passed"}:
                    state_status = "completed"
                elif normalized_status in {"skipped", "not_required"}:
                    state_status = "skipped"
                elif normalized_status in {"failed", "blocked", "planner_failed", "code_generation_failed"}:
                    state_status = "failed"
                else:
                    state_status = "completed" if stage_index > 1 else "running"
                stage_step = self._runtime_state_stage_step(stage)
                runtime_state_manager.emit(
                    run_id=run_id,
                    step_id=stage_step,
                    level="developer",
                    kind="lifecycle" if state_status == "running" else ("error" if state_status == "failed" else "output"),
                    status=state_status,
                    title=stage,
                    message=f"{stage}: {status}",
                    input={"stage": stage} if stage_index == 1 else None,
                    output={k: v for k, v in data.items() if k not in {"template", "planner"}},
                    method="capability_acquisition",
                    progress=100.0 if state_status in {"completed", "skipped"} else progress_hint,
                    trace={"pipeline_stage_index": stage_index},
                    next_action=self._runtime_state_next_action(stage, state_status),
                )
            except Exception:
                pass

        mark("CapabilityAcquisitionRouter", "accepted" if allow_implementation else "not_requested", user_input_excerpt=str(user_input or "")[:1000], evidence_keys=sorted(list(evidence.keys())) if isinstance(evidence, dict) else [])
        try:
            self.trace_logger.write_snapshot(run_id=run_id, name="00_router_input", payload={"user_input": user_input, "evidence": evidence, "allow_implementation": allow_implementation})
        except Exception:
            pass
        if not allow_implementation:
            return {"status": "not_requested", "reason": "implementation_was_not_requested", "pipeline": pipeline}

        event_contract = self._extract_need_capability_event_contract(evidence)
        mark("NeedCapabilityContract", "accepted" if event_contract else "missing", contract_version=event_contract.get("contract_version") if isinstance(event_contract, dict) else None)

        identity_contract = self._extract_requested_identity_contract(user_input)
        mark("CapabilityIdentityExtractor", "completed", identity=identity_contract)

        urls = evidence.get("urls") if isinstance(evidence.get("urls"), list) else []
        match: TemplateMatch | None = None
        template_source = "runtime_blueprint_planner"
        planner_record: dict[str, Any] | None = None

        # v16: template-less acquisition is the default. The small/runtime model
        # creates a neutral blueprint, then ai_core materializes and verifies it.
        # Existing runtime templates may be used only when explicitly enabled for
        # compatibility by AI_CORE_ALLOW_TEMPLATE_FALLBACK=true.
        mark("TemplateResolver", "skipped", reason="template_less_blueprint_generation_is_default")
        # Capability acquisition has its own lifecycle and must keep the
        # original acquisition pipeline semantics.  It is not a scheduled/task
        # execution path, so it must not be wrapped in a secondary worker that
        # can detach the blueprint planner/materializer from the acquisition
        # state machine.  Long-running protection is handled by the outer
        # capability-acquisition job policy, not by splitting this stage again.
        planner_record = self._plan_capability_with_runtime_planner(
            user_input=user_input, identity_contract=identity_contract, evidence=evidence, event_contract=event_contract, state_run_id=run_id
        )
        mark("BlueprintPlanner", str(planner_record.get("status") or "planner_failed"), planner=planner_record)

        if planner_record.get("status") == "planned" and isinstance(planner_record.get("template"), dict):
            template = self._merge_identity_contract_into_template(dict(planner_record["template"]), identity_contract)
            persisted_template = self._persist_runtime_planned_template(template=template, run_id=run_id, planner_record=planner_record)
            mark("BlueprintMaterializer", "completed" if persisted_template.get("passed") else "failed", result=persisted_template)
            match = TemplateMatch(template=template, score=int(float(planner_record.get("confidence_score") or 1) * 100))
        else:
            if self._allow_template_fallback():
                templates = self._load_templates()
                match = self._select_template(str(user_input or ""), templates)
                if match:
                    template = self._merge_identity_contract_into_template(match.template, identity_contract)
                    template_source = "compatibility_template_fallback"
                    mark("TemplateFallback", "matched", template_id=template.get("template_id"), score=match.score)
                else:
                    mark("TemplateFallback", "not_found", template_locations=[str(p) for p in self.template_store.candidate_paths()])
            if not match:
                repair = self._runtime_self_repair(
                    run_id=run_id,
                    stage="BlueprintPlanner",
                    status=str(planner_record.get("status") or "planner_failed"),
                    reason=str(planner_record.get("reason") or "planner_did_not_return_blueprint"),
                    payload={"identity": identity_contract, "planner": planner_record},
                    expected={"required_status": "planned", "required_payload": "blueprint_or_template"},
                )
                mark("RuntimeSelfRepairEngine", str(repair.get("status") or "repair_checked"), repair=repair)
                return {
                    "status": str(planner_record.get("status") or "planner_failed"),
                    "reason": str(planner_record.get("reason") or "blueprint_planner_failed"),
                    "requested_identity_contract": identity_contract,
                    "pipeline": pipeline,
                    "self_repair": repair,
                    "evidence_present": bool(urls),
                    "diagnosis": "blueprint_planner_failed_after_verified_evidence" if urls else "blueprint_planner_failed_before_verified_evidence",
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }

        acquisition_policy = template.get("acquisition_policy") if isinstance(template.get("acquisition_policy"), dict) else {}
        runtime_native_decision = self._classify_runtime_native_acquisition(user_input=user_input, template=template, planner_record=planner_record or {}, evidence=evidence)
        mark("CapabilityAcquisitionClass", str(runtime_native_decision.get("class") or "unknown"), decision=runtime_native_decision)
        if runtime_native_decision.get("runtime_native"):
            acquisition_policy = dict(acquisition_policy)
            acquisition_policy["allow_policy_backed_basic_acquisition_without_external_evidence"] = True
            acquisition_policy["runtime_native_policy_backed"] = True
            template["acquisition_policy"] = acquisition_policy
            if planner_record is not None:
                planner_record["needs_external_evidence"] = False
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
            evidence["urls"] = ["runtime-policy://basic-runtime-capability-contract"]
            evidence["source_note"] = "Policy-backed runtime acquisition without external source material."

        # Preserve explicitly declared interface and verification facts from the
        # acquisition request after the runtime planner has produced a template.
        # This is contract-driven and generic: it does not infer any concrete
        # service behavior; it only prevents planner/model loss of user-declared
        # schemas, identity, approval policy, and match requirements.
        template = self._augment_blueprint_from_user_request(dict(template), user_input=user_input)
        template = self._merge_identity_contract_into_template(template, identity_contract)

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

        dependency_resolution = self._resolve_artifact_dependencies(template=template, artifact=artifact, previous=dependency_resolution)
        mark(
            "ArtifactDependencyResolver",
            "completed" if dependency_resolution.get("passed") else str(dependency_resolution.get("status") or "failed"),
            result=dependency_resolution,
        )
        if not dependency_resolution.get("passed"):
            repair = self._runtime_self_repair(
                run_id=run_id,
                stage="ArtifactDependencyResolver",
                status=str(dependency_resolution.get("status") or "failed"),
                reason="artifact_dependency_resolution_failed",
                payload=dependency_resolution,
                expected={"passed": True},
            )
            mark("RuntimeSelfRepairEngine", str(repair.get("status") or "repair_checked"), repair=repair)
            return {
                "status": "dependency_resolution_failed",
                "template_id": template.get("template_id"),
                "score": match.score if match else 0,
                "dependency_resolution": dependency_resolution,
                "artifact": artifact,
                "pipeline": pipeline,
                "self_repair": repair,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }

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

        validation = self._validate_artifact(artifact)
        mark("SandboxValidator", "completed" if validation.get("passed") else "sandbox_failed", result=validation)
        if not validation.get("passed"):
            retry = self._retry_artifact_after_validation_failure(
                template=template,
                planner_record=planner_record or {},
                identity_contract=identity_contract,
                validation=validation,
                run_id=run_id,
                evidence=evidence,
                dependency_resolution=dependency_resolution,
                user_input=user_input,
            )
            mark("SandboxRepairGenerator", str(retry.get("status") or "not_attempted"), result=retry)
            if retry.get("status") == "validation_passed":
                template = retry["template"]
                artifact = retry["artifact"]
                dependency_resolution = retry["dependency_resolution"]
                pre_gate = retry["pre_gate"]
                capability_match = retry["capability_match"]
                validation = retry["validation"]
        verification_run: dict[str, Any] | None = None
        if validation.get("passed"):
            if str(validation.get("isolation_level") or "").strip().lower() == "static_only":
                verification_run = {
                    "passed": True,
                    "status": "static_validation_only",
                    "reason": "Sandbox policy selected static-only validation; live verification is deferred until runtime profile values are configured.",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            else:
                verification_run = self._execute_verification_run(template=template, artifact=artifact)
            mark("VerificationRun", "completed" if verification_run.get("passed") else "failed", result=verification_run)

        registration_gate = self.acquisition_gate.evaluate_before_registration(
            pre_validation_decision=pre_gate,
            validation=validation,
            verification_run=verification_run or {},
        )
        self.acquisition_gate.write_report(artifact_dir=artifact.get("tool_dir"), report={"pre_validation": pre_gate, "registration": registration_gate})
        mark("RegistrationGate", "safe_to_register" if registration_gate.get("safe_to_register") else str(registration_gate.get("status") or "blocked"), result=registration_gate)

        registration: dict[str, Any] | None = None
        interaction_request: dict[str, Any] | None = None
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
            status = str((registration or {}).get("status") or "registered")
            interaction_request = self._build_live_verification_interaction_request(registration=registration or {}, run_id=run_id, session_id="")
            if interaction_request:
                mark("LiveVerificationInteraction", "requested", request=interaction_request)
            repair = None
        else:
            failure_status = "sandbox_failed" if not validation.get("passed") else "not_registered"
            repair = self._runtime_self_repair(
                run_id=run_id,
                stage="SandboxValidator" if not validation.get("passed") else "RegistrationGate",
                status=failure_status,
                reason=str(registration_gate.get("reason") or failure_status),
                payload={"validation": validation, "verification_run": verification_run, "registration_gate": registration_gate},
                expected={"safe_to_register": True},
            )
            mark("RuntimeSelfRepairEngine", str(repair.get("status") or "repair_checked"), repair=repair)
            status = failure_status

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
            "interaction_request": interaction_request,
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


    def _extract_need_capability_event_contract(self, evidence: dict[str, Any]) -> dict[str, Any]:
        """Read ai_core's authoritative planning contract from evidence.

        auxiliary_brain consumes this contract for schema/implementation planning;
        it must not redo ai_core intent recognition or missing-information logic.
        """
        event = evidence.get("need_capability_event") if isinstance(evidence, dict) else None
        if not isinstance(event, dict):
            return {}
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if not payload:
            return {}
        boundary = payload.get("acquisition_boundary") if isinstance(payload.get("acquisition_boundary"), dict) else {}
        if boundary and boundary.get("auxiliary_brain_must_not_reinfer_intent") is not True:
            payload = dict(payload)
            payload["acquisition_boundary_warning"] = "missing_no_reinfer_contract"
        return payload

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




    def _runtime_state_stage_step(self, stage: str) -> str:
        value = str(stage or "capability_stage")
        aliases = {
            "CapabilityAcquisitionRouter": "intent_recognition.capability_acquisition",
            "NeedCapabilityContract": "intent_recognition.capability_contract",
            "CapabilityIdentityExtractor": "input_parsing.capability_identity",
            "TemplateResolver": "workflow.capability_template_resolution",
            "BlueprintPlanner": "workflow.capability_blueprint_planning",
            "BlueprintMaterializer": "workflow.capability_blueprint_materialization",
            "CapabilityAcquisitionClass": "pre_execution.capability_classification",
            "WebEvidenceRetriever": "evidence.capability_material",
            "DependencyResolver": "dependency.resolution",
            "ArtifactGenerator": "execution.artifact_generation",
            "ArtifactDependencyResolver": "dependency.artifact_resolution",
            "AcquisitionGate": "pre_execution.acquisition_gate",
            "CapabilityMatchContract": "verification.capability_match_contract",
            "SandboxValidator": "validation.sandbox",
            "VerificationRun": "result.verify.capability_execution",
            "RegistrationGate": "pre_execution.registration_gate",
            "RegistryWriter": "execution.registry_write",
            "LiveVerificationInteraction": "final.capability_verification",
            "RuntimeSelfRepairEngine": "repair.capability_acquisition",
        }
        return aliases.get(value, "capability." + self._safe_name(value))

    def _runtime_state_next_action(self, stage: str, state_status: str) -> str:
        if state_status == "failed":
            return "inspect failure payload and allowed repair policy"
        order = [
            "CapabilityAcquisitionRouter",
            "NeedCapabilityContract",
            "CapabilityIdentityExtractor",
            "TemplateResolver",
            "BlueprintPlanner",
            "BlueprintMaterializer",
            "CapabilityAcquisitionClass",
            "WebEvidenceRetriever",
            "DependencyResolver",
            "ArtifactGenerator",
            "ArtifactDependencyResolver",
            "AcquisitionGate",
            "CapabilityMatchContract",
            "SandboxValidator",
            "VerificationRun",
            "RegistrationGate",
            "RegistryWriter",
            "LiveVerificationInteraction",
        ]
        try:
            idx = order.index(str(stage or ""))
            return order[idx + 1] if idx + 1 < len(order) else "finalize runtime result"
        except ValueError:
            return ""

    def _plan_capability_with_runtime_planner(
        self,
        *,
        user_input: str,
        identity_contract: dict[str, Any],
        evidence: dict[str, Any],
        event_contract: dict[str, Any] | None = None,
        state_run_id: str = "",
    ) -> dict[str, Any]:
        """Invoke a runtime-configured planner hook for template-less acquisition.

        ai_core only defines the neutral contract.  A concrete planner can be
        supplied at runtime with AI_CORE_CAPABILITY_PLANNER as
        "module.path:function_name".  The hook must return a dict containing a
        template compatible with the runtime capability template schema.
        """
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
            with self.stage_observer.span(run_id=state_run_id or "capability_planner", stage_id="workflow.capability_blueprint_planning", area="capability_acquisition", metadata={"planner_origin": planner_origin}) as span:
                payload = planner({
                    "user_input": user_input,
                    "identity_contract": identity_contract,
                    "evidence": evidence,
                    "need_capability_event_contract": event_contract or {},
                    "ai_core_boundary_contract": {
                        "intent_and_workflow_are_authoritative": bool(event_contract),
                        "do_not_reinfer_intent_from_user_input": bool(event_contract),
                        "derive_schema_from": ["need_capability_event_contract.workflow_contract", "need_capability_event_contract.capability_constraints"],
                    },
                    "required_template_contract": self._runtime_planner_template_contract(),
                    "required_blueprint_contract": self._runtime_planner_template_contract(),
                    "planner_origin": planner_origin,
                })
            if not isinstance(payload, dict):
                return {"status": "planner_failed", "reason": "planner_returned_non_object", "confidence_score": 0, "needs_external_evidence": True}
            raw_blueprint = payload.get("blueprint") if isinstance(payload.get("blueprint"), dict) else payload.get("template")
            confidence = float(payload.get("confidence_score") or payload.get("confidence") or 0)
            if not isinstance(raw_blueprint, dict):
                return {"status": "planner_failed", "reason": "planner_returned_no_blueprint", "confidence_score": confidence, "needs_external_evidence": True, "raw": payload}
            raw_blueprint = self._augment_blueprint_from_user_request(raw_blueprint, user_input=user_input)
            template = self.blueprint_artifact_generator.materialize(raw_blueprint, identity_contract=identity_contract)
            code_generation = template.get("code_generation") if isinstance(template.get("code_generation"), dict) else {}
            if template.get("artifact_kind") != "real_runtime_implementation":
                return {
                    "status": "code_generation_failed",
                    "reason": str(code_generation.get("error") or code_generation.get("status") or "runtime_artifact_not_registerable"),
                    "confidence_score": confidence,
                    "needs_external_evidence": False,
                    "template": template,
                    "code_generation": code_generation,
                }
            validation = self._validate_runtime_template_shape(template)
            if not validation.get("passed"):
                return {"status": "planner_failed", "reason": "planner_blueprint_contract_failed", "confidence_score": confidence, "needs_external_evidence": True, "validation": validation}
            min_confidence = float(os.environ.get("AI_CORE_CAPABILITY_PLANNER_MIN_CONFIDENCE", "0.70") or 0.70)
            policy_backed_basic = self._request_declares_policy_backed_basic(user_input=user_input, template=template, evidence=evidence)
            if policy_backed_basic:
                policy = template.get("acquisition_policy") if isinstance(template.get("acquisition_policy"), dict) else {}
                policy = dict(policy)
                policy["allow_policy_backed_basic_acquisition_without_external_evidence"] = True
                policy["planner_confidence_policy_override"] = confidence < min_confidence
                template["acquisition_policy"] = policy
            if confidence < min_confidence and not policy_backed_basic:
                return {"status": "planner_low_confidence", "reason": "planner_confidence_below_threshold", "confidence_score": confidence, "needs_external_evidence": True, "template": template, "validation": validation}
            return {
                "status": "planned",
                "confidence_score": confidence,
                "needs_external_evidence": False if policy_backed_basic else bool(payload.get("needs_external_evidence")),
                "template": template,
                "blueprint": raw_blueprint,
                "validation": validation,
                "planner_origin": planner_origin,
                "policy_backed_basic": policy_backed_basic,
            }
        except ValueError:
            return {
                "status": "planner_failed",
                "reason": "planner_hook_must_use_module_colon_function_format",
                "confidence_score": 0,
                "needs_external_evidence": True,
                "planner_origin": planner_origin,
            }
        except Exception as exc:
            return {
                "status": "planner_failed",
                "reason": f"{exc.__class__.__name__}: {str(exc)[:500]}",
                "confidence_score": 0,
                "needs_external_evidence": True,
            }



    def _augment_blueprint_from_user_request(self, blueprint: dict[str, Any], *, user_input: str) -> dict[str, Any]:
        """Add explicitly declared user contract details to planner output.

        This is not domain logic.  It only preserves explicit schema/contract text
        that the user already declared, preventing a weak planner from replacing
        the requested interface with the generic operation/name management schema.
        """
        merged = dict(blueprint or {})
        text = str(user_input or "")
        existing_description = str(merged.get("description") or "")
        merged["description"] = (existing_description + "\n" + text[:4000]).strip()
        declared_input = self._extract_declared_schema_section(text, header_patterns=[r"Input\s+schema\s+must\s+include(?:\s+only)?", r"Input\s+parameters?"])
        if declared_input:
            merged["input_schema"] = declared_input
        declared_connection = self._extract_declared_schema_section(text, header_patterns=[r"Connection\s+schema\s+must\s+include(?:\s+only)?", r"Connection\s+parameters?"])
        if declared_connection:
            merged["connection_schema"] = declared_connection
        declared_secret = self._extract_declared_schema_section(text, header_patterns=[r"Secret\s+schema\s+must\s+include(?:\s+only)?", r"Secret\s+parameters?"])
        if declared_secret:
            merged["secret_schema"] = declared_secret
        declared_output_fields = self._extract_declared_field_names(text, header_patterns=[r"Output\s+fields?"])
        if declared_output_fields and not self._schema_has_specific_properties(merged.get("output_schema")):
            merged["output_schema"] = {
                "type": "object",
                "required": ["status", "data"],
                "properties": {
                    "status": {"type": "string"},
                    "data": {"type": "object", "properties": {name: {"type": "string"} for name in declared_output_fields}, "additionalProperties": True},
                    "message": {"type": "string"},
                    "provenance": {"type": "object"},
                },
                "additionalProperties": False,
            }
        declared_policy = self._extract_declared_approval_policy(text)
        if declared_policy:
            merged["approval_policy"] = declared_policy
            execution_policy = dict(merged.get("runtime_execution_policy") if isinstance(merged.get("runtime_execution_policy"), dict) else {})
            execution_policy["approval_policy"] = declared_policy
            merged["runtime_execution_policy"] = execution_policy
        contract = dict(merged.get("capability_match_contract") if isinstance(merged.get("capability_match_contract"), dict) else {})
        contract_markers = self._extract_declared_match_markers(text)
        if contract_markers:
            existing = contract.get("required_markers") if isinstance(contract.get("required_markers"), list) else []
            contract["required_markers"] = list(dict.fromkeys([*existing, *contract_markers]))
        declared_interface = {
            "input_schema": declared_input,
            "connection_schema": declared_connection,
            "secret_schema": declared_secret,
            "approval_policy": declared_policy,
        }
        contract["declared_interface"] = {k: v for k, v in declared_interface.items() if v}
        if contract:
            merged["capability_match_contract"] = contract
        return merged

    def _extract_declared_approval_policy(self, text: str) -> dict[str, Any]:
        lines = str(text or "").splitlines()
        in_section = False
        modes: list[str] = []
        default_mode = ""
        for raw in lines:
            line = raw.strip().strip("-* ")
            if re.search(r"approval\s+policy", line, flags=re.IGNORECASE):
                in_section = True
            elif in_section and re.match(r"^[A-Za-z].*:$", line) and not re.search(r"support|default|mode", line, flags=re.IGNORECASE):
                break
            if not in_section:
                continue
            support_match = re.search(r"support\s+([a-zA-Z0-9_\-]+)", line, flags=re.IGNORECASE)
            if support_match:
                mode = support_match.group(1).strip().casefold()
                if mode and mode not in modes:
                    modes.append(mode)
            default_match = re.search(r"default\s+(?:mode\s*)?[:：]?\s*([a-zA-Z0-9_\-]+)", line, flags=re.IGNORECASE)
            if default_match:
                default_mode = default_match.group(1).strip().casefold()
        if not modes and not default_mode:
            return {}
        if default_mode and default_mode not in modes:
            modes.append(default_mode)
        return {"supported_modes": modes, "default_mode": default_mode or (modes[0] if modes else "")}

    def _extract_declared_match_markers(self, text: str) -> list[str]:
        markers: list[str] = []
        for raw in str(text or "").splitlines():
            line = raw.strip().strip("-* ")
            if not re.search(r"\bverify\b", line, flags=re.IGNORECASE):
                continue
            for pattern in [
                r"\bis\s+([^.;。]+)$",
                r"\bunder\s+([^.;。]+)$",
                r"\bas\s+([^.;。]+)$",
                r"\bon\s+port\s+([0-9]+)",
                r"\buse\s+([^.;。]+)$",
            ]:
                match = re.search(pattern, line, flags=re.IGNORECASE)
                if match:
                    value = match.group(1).strip().strip("`'\"")
                    if value and len(value) <= 120 and value.casefold() not in {"true", "false", "completed", "passed"}:
                        markers.append(value)
                    break
        return list(dict.fromkeys(markers))

    def _section_declares_only(self, text: str, header_patterns: list[str]) -> bool:
        lines = str(text or "").splitlines()
        for raw in lines:
            line = raw.strip()
            if any(re.search(pattern, line, flags=re.IGNORECASE) for pattern in header_patterns):
                return bool(re.search(r"\bonly\b", line, flags=re.IGNORECASE))
        return False

    def _schema_has_specific_properties(self, value: Any) -> bool:
        if not isinstance(value, dict):
            return False
        props = value.get("properties") if isinstance(value.get("properties"), dict) else {}
        generic = {"operation", "name", "definition", "patch", "enabled", "dry_run"}
        return bool(set(props) - generic)

    def _extract_declared_schema_section(self, text: str, *, header_patterns: list[str]) -> dict[str, Any]:
        names = self._extract_declared_field_names(text, header_patterns=header_patterns)
        if not names:
            return {}
        props: dict[str, Any] = {}
        required: list[str] = []
        lowered = text.casefold()
        for name in names:
            props[name] = {"type": "string"}
            pattern = re.compile(rf"{re.escape(name)}\s*[:：-]?\s*([^\n]*)", flags=re.IGNORECASE)
            match = pattern.search(text)
            detail = (match.group(1) if match else "").casefold()
            # Boundary rule: a schema section that says "must include" only declares
            # field existence. It does not mean every field is mandatory at runtime.
            # A field becomes required only when the field line explicitly says so,
            # or when a default is absent and the planner/code later proves it is
            # structurally required. This keeps ai_core generic and prevents optional
            # values from becoming forced UI inputs.
            explicitly_required = any(marker in detail for marker in [
                "required", "mandatory", "must provide", "must be provided",
                "must supply", "must be supplied", "not optional",
            ])
            if explicitly_required and "optional" not in detail and "default" not in detail:
                required.append(name)
            if "boolean" in detail or "true" in detail or "false" in detail:
                props[name]["type"] = "boolean"
            elif "integer" in detail or "number" in detail:
                props[name]["type"] = "number"
            elif str(name).casefold() in {"attachments", "files", "file_paths"} or str(name).casefold().endswith("s") and any(token in str(name).casefold() for token in ["file", "attachment", "path"]):
                props[name]["type"] = "array"
                props[name]["items"] = {"type": "string"}
            if "default" in detail:
                # Preserve the original spelling/case of explicit defaults.
                # The lower-cased detail string is only for keyword detection;
                # using it as the source value turns user contracts like
                # `YYYY-MM-DD HH:mm` into `yyyy-mm-dd` and can break generic
                # runtime format handling.  Capture until a sentence delimiter
                # or parenthesized clause, while allowing spaces inside values.
                raw_detail = match.group(1) if match else ""
                default_match = re.search(
                    r"default\s+(.+?)(?:\s*[.;。]|\s+\(|$)",
                    raw_detail,
                    flags=re.IGNORECASE,
                )
                if default_match:
                    props[name]["default"] = default_match.group(1).strip().strip("`'\"")
        if "dry_run" not in props and "dry_run" in lowered:
            props["dry_run"] = {"type": "boolean", "default": False}
        return {"type": "object", "required": required, "properties": props, "additionalProperties": False}

    def _extract_declared_field_names(self, text: str, *, header_patterns: list[str]) -> list[str]:
        lines = str(text or "").splitlines()
        names: list[str] = []
        active = False
        for raw in lines:
            line = raw.strip()
            section_line = re.sub(r"^[-*]\s*", "", line).strip()
            if any(re.search(pattern, line, flags=re.IGNORECASE) for pattern in header_patterns):
                active = True
                continue
            if active and re.match(r"^[A-Z][A-Za-z ]+requirements?\s*[:：]?$", section_line):
                break
            if active and re.match(r"^(Input\s+(?:schema|parameters?)(?:\s+must\s+include(?:\s+only)?)?|Connection\s+(?:schema|parameters?)(?:\s+must\s+include(?:\s+only)?)?|Secret\s+(?:schema|parameters?)(?:\s+must\s+include(?:\s+only)?)?|Output\s+fields?|Approval\s+policy|Verification\s+requirements?|Capability\s+behavior\s+requirements?)\s*[:：]?$", section_line, flags=re.IGNORECASE):
                break
            if active and re.match(r"^The\s+capability\s+acquisition\s+is\s+complete", section_line, flags=re.IGNORECASE):
                break
            if not active:
                continue
            match = re.match(r"^[-*]\s*([a-zA-Z_][a-zA-Z0-9_]*)\b", line)
            if match:
                value = self._safe_name(match.group(1))
                if value and value not in names:
                    names.append(value)
            elif line and not line.startswith(("-", "*")) and ":" in line:
                head = line.split(":", 1)[0].strip()
                value = self._safe_name(head)
                if value and value not in names:
                    names.append(value)
        return names

    def _allow_template_fallback(self) -> bool:
        return str(os.environ.get("AI_CORE_ALLOW_TEMPLATE_FALLBACK", "")).strip().casefold() in {"1", "true", "yes", "on"}

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

    def _classify_runtime_native_acquisition(self, *, user_input: str, template: dict[str, Any], planner_record: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
        """Delegate runtime-native classification to the acquisition classification layer."""
        return self.capability_classifier.classify(
            user_input=user_input,
            template=template,
            planner_record=planner_record,
            evidence=evidence,
        )

    def _request_declares_policy_backed_basic(self, *, user_input: str, template: dict[str, Any], evidence: dict[str, Any]) -> bool:
        """Delegate local-only policy detection to the acquisition classification layer."""
        return self.capability_classifier.is_policy_backed_basic(
            user_input=user_input,
            template=template,
            evidence=evidence,
        )

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

    def _resolve_artifact_dependencies(
        self,
        *,
        template: dict[str, Any],
        artifact: dict[str, Any],
        previous: dict[str, Any],
    ) -> dict[str, Any]:
        """Resolve dependencies that are visible only after code generation."""
        declared = self._normalized_dependencies(template.get("dependencies"))
        discovered = self._discover_artifact_python_dependencies(artifact, declared)
        merged = self._merge_dependencies(declared, discovered)
        if not discovered:
            self._update_artifact_dependency_manifest(artifact=artifact, dependencies=merged, dependency_resolution=previous)
            return {
                **previous,
                "dependencies": merged,
                "artifact_dependency_scan": {"status": "completed", "discovered": []},
            }
        resolution = self._resolve_dependencies({"dependencies": merged})
        combined = {
            "passed": bool(resolution.get("passed")),
            "status": resolution.get("status"),
            "checks": resolution.get("checks", []),
            "pre_generation": previous,
            "dependencies": merged,
            "artifact_dependency_scan": {
                "status": "completed",
                "discovered": discovered,
            },
        }
        template["dependencies"] = merged
        self._update_artifact_dependency_manifest(artifact=artifact, dependencies=merged, dependency_resolution=combined)
        return combined

    def _discover_artifact_python_dependencies(self, artifact: dict[str, Any], declared: list[dict[str, Any]]) -> list[dict[str, Any]]:
        tool_dir = Path(str(artifact.get("tool_dir") or ""))
        test_dir = Path(str(artifact.get("test_dir") or ""))
        if not tool_dir.exists():
            return []
        local_modules = {path.stem for path in tool_dir.rglob("*.py")}
        if test_dir.exists():
            local_modules.update(path.stem for path in test_dir.rglob("*.py"))
        declared_imports = self._dependency_import_names(declared)
        discovered: list[dict[str, Any]] = []
        seen: set[str] = set()
        python_files = list(tool_dir.rglob("*.py"))
        if test_dir.exists():
            python_files.extend(test_dir.rglob("*.py"))
        for path in sorted({p.resolve() for p in python_files}):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for module in self._top_level_imports(tree):
                if not module:
                    continue
                if module in local_modules or module in declared_imports or module in getattr(sys, "stdlib_module_names", set()):
                    continue
                if module in seen:
                    continue
                seen.add(module)
                discovered.append({
                    "package": module,
                    "import_name": module,
                    "auto_install": True,
                    "source": "artifact_import_scan",
                })
        return discovered

    def _update_artifact_dependency_manifest(
        self,
        *,
        artifact: dict[str, Any],
        dependencies: list[dict[str, Any]],
        dependency_resolution: dict[str, Any],
    ) -> None:
        manifest_path = Path(str(artifact.get("manifest_path") or ""))
        if not manifest_path.exists():
            return
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(manifest, dict):
            return
        manifest["dependencies"] = dependencies
        manifest["dependency_resolution"] = dependency_resolution
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    def _normalized_dependencies(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        result: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            import_name = str(item.get("import_name") or item.get("module") or "").strip()
            package = str(item.get("package") or item.get("name") or import_name).strip()
            if not package and not import_name:
                continue
            result.append({
                "package": package or import_name,
                "import_name": import_name or package.replace("-", "_"),
                "auto_install": bool(item.get("auto_install", True)),
                **({"source": item.get("source")} if item.get("source") else {}),
            })
        return result

    def _merge_dependencies(self, left: list[dict[str, Any]], right: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in [*left, *right]:
            package = str(item.get("package") or item.get("name") or "").strip()
            import_name = str(item.get("import_name") or item.get("module") or "").strip()
            key = (package, import_name)
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
        return merged

    def _dependency_import_names(self, dependencies: list[dict[str, Any]]) -> set[str]:
        imports: set[str] = set()
        for item in dependencies:
            import_name = str(item.get("import_name") or item.get("module") or "").strip()
            package = str(item.get("package") or item.get("name") or "").strip()
            if import_name:
                imports.add(import_name.split(".", 1)[0])
            elif package:
                imports.add(package.replace("-", "_").split(".", 1)[0])
        return imports

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
        for item in [base_executable, sys.executable, "python", "python3"]:
            value = str(item or "").strip()
            if value and value not in candidates:
                candidates.append(value)
        return candidates

    def _run_isolated_python(self, args: list[str], *, cwd: Path, timeout: int = 30, pythonpath: str | None = None) -> dict[str, Any]:
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
                    encoding="utf-8",
                    errors="replace",
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
                encoding="utf-8",
                errors="replace",
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
        # A capability acquisition run must be isolated.  Never reuse files,
        # schemas, or manifests left by a previous capability with the same id.
        if tool_dir.exists():
            shutil.rmtree(tool_dir)
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
        if tests_dir.exists():
            shutil.rmtree(tests_dir)
        tests_dir.mkdir(parents=True, exist_ok=True)
        test_files: list[str] = []
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
            "runtime_execution_policy": template.get("runtime_execution_policy") if isinstance(template.get("runtime_execution_policy"), dict) else {},
            "artifact_kind": template.get("artifact_kind") or "unknown",
            "verification_input": template.get("verification_input") if isinstance(template.get("verification_input"), dict) else {},
            "verification_expectations": template.get("verification_expectations") if isinstance(template.get("verification_expectations"), dict) else {},
            "specification_contract": template.get("specification_contract") if isinstance(template.get("specification_contract"), dict) else {},
            "written_files": written,
            "test_dir": str(tests_dir),
            "test_files": test_files,
        }
        manifest_path = tool_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        generated_test = self._generic_contract_test_source(tool_dir=tool_dir, manifest_path=manifest_path)
        test_target = tests_dir / "test_contract_smoke.py"
        test_target.write_text(generated_test, encoding="utf-8")
        test_files.append(str(test_target))
        manifest["test_files"] = test_files
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"tool_id": safe_id, "tool_dir": str(tool_dir), "test_dir": str(tests_dir), "manifest_path": str(manifest_path), "written_files": written, "test_files": test_files}

    def _generic_contract_test_source(self, *, tool_dir: Path, manifest_path: Path) -> str:
        return """import importlib.util
import json
from pathlib import Path

TOOL_DIR = Path(%r)
MANIFEST_PATH = Path(%r)


def test_runtime_contract_smoke():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    entrypoint = manifest.get("entrypoint") or {}
    module_path = TOOL_DIR / str(entrypoint.get("module") or "tool.py")
    function_name = str(entrypoint.get("function") or "run")
    payload = manifest.get("verification_input") if isinstance(manifest.get("verification_input"), dict) else {}
    runtime = payload.setdefault("_runtime", {})
    if isinstance(runtime, dict):
        runtime.setdefault("dry_run", True)
    spec = importlib.util.spec_from_file_location("runtime_generated_tool_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = getattr(module, function_name)(payload)
    assert result is not None, "entrypoint_returned_none_not_dict"
    assert isinstance(result, dict), f"entrypoint_returned_non_dict:{type(result).__name__}"
    json.dumps(result, ensure_ascii=False)
    status = str(result.get("status") or "").lower()
    assert status not in {"error", "failure", "failed"}, result
""" % (str(tool_dir), str(manifest_path))

    def _retry_artifact_after_validation_failure(
        self,
        *,
        template: dict[str, Any],
        planner_record: dict[str, Any],
        identity_contract: dict[str, Any],
        validation: dict[str, Any],
        run_id: str,
        evidence: dict[str, Any],
        dependency_resolution: dict[str, Any],
        user_input: str,
    ) -> dict[str, Any]:
        if not self._validation_failure_is_regenerable(validation):
            return {"status": "not_attempted", "reason": "validation_failure_not_regenerable"}
        source_blueprint = planner_record.get("blueprint") if isinstance(planner_record.get("blueprint"), dict) else template
        repair_blueprint = dict(source_blueprint)
        for key in [
            "template_id",
            "capabilities",
            "entrypoint",
            "input_schema",
            "output_schema",
            "connection_schema",
            "secret_schema",
            "approval_policy",
            "runtime_interface",
            "runtime_execution_policy",
            "verification_input",
            "verification_expectations",
            "capability_match_contract",
            "acquisition_policy",
            "dependencies",
        ]:
            if key in template:
                repair_blueprint[key] = template[key]
        repair_blueprint["files"] = []
        repair_blueprint["previous_validation_failure"] = self._compact_validation_failure(validation)
        repair_blueprint["description"] = (
            str(repair_blueprint.get("description") or "")
            + "\n\nPrevious generated artifact failed sandbox validation. "
            "Regenerate the runtime files so tests are self-contained, all names are imported or defined, "
            "the entrypoint output is JSON-serializable, and the verification behavior follows the sandbox execution policy. "
            "If the artifact requires live preset connection values, secrets, credentials, accounts, or external side effects, sandbox validation must remain static-only. If it can be exercised with sandbox-owned local inputs, tests may execute without external effects."
        ).strip()
        repaired_template = self.blueprint_artifact_generator.materialize(repair_blueprint, identity_contract=identity_contract)
        if repaired_template.get("artifact_kind") != "real_runtime_implementation":
            return {
                "status": "code_generation_failed",
                "reason": "repair_generation_did_not_produce_runtime_implementation",
                "code_generation": repaired_template.get("code_generation") if isinstance(repaired_template.get("code_generation"), dict) else {},
            }
        shape = self._validate_runtime_template_shape(repaired_template)
        if not shape.get("passed"):
            return {"status": "planner_failed", "reason": "repair_template_contract_failed", "validation": shape}
        repaired_artifact = self._write_artifact(template=repaired_template, run_id=run_id, evidence=evidence, dependency_resolution=dependency_resolution)
        repaired_dependency_resolution = self._resolve_artifact_dependencies(
            template=repaired_template,
            artifact=repaired_artifact,
            previous=dependency_resolution,
        )
        if not repaired_dependency_resolution.get("passed"):
            return {
                "status": "dependency_resolution_failed",
                "dependency_resolution": repaired_dependency_resolution,
                "artifact": repaired_artifact,
            }
        repaired_pre_gate = self.acquisition_gate.evaluate_before_validation(
            requested_capability=str(repaired_template.get("template_id") or ""),
            user_input=user_input,
            template=repaired_template,
            artifact=repaired_artifact,
            dependency_resolution=repaired_dependency_resolution,
        )
        self.acquisition_gate.write_report(artifact_dir=repaired_artifact.get("tool_dir"), report={"pre_validation": repaired_pre_gate})
        repaired_match = self._verify_capability_match(template=repaired_template, artifact=repaired_artifact, user_input=user_input)
        if not repaired_pre_gate.get("passed") or not repaired_match.get("passed"):
            return {
                "status": "generated_but_capability_mismatch",
                "pre_gate": repaired_pre_gate,
                "capability_match": repaired_match,
                "artifact": repaired_artifact,
            }
        repaired_validation = self._validate_artifact(repaired_artifact)
        return {
            "status": "validation_passed" if repaired_validation.get("passed") else "validation_failed",
            "template": repaired_template,
            "artifact": repaired_artifact,
            "dependency_resolution": repaired_dependency_resolution,
            "pre_gate": repaired_pre_gate,
            "capability_match": repaired_match,
            "validation": repaired_validation,
        }

    def _validation_failure_is_regenerable(self, validation: dict[str, Any]) -> bool:
        reason = str(validation.get("reason") or "").strip()
        if reason in {
            "generated_test_undefined_names",
            "undeclared_external_test_dependencies",
            "entrypoint_output_not_json_serializable_or_execution_failed",
            "entrypoint_smoke_test_failed",
            "entrypoint_returned_none_not_dict",
            "output_is_not_object",
            "artifact_quality_gate_failed",
        }:
            return True
        checks = validation.get("checks") if isinstance(validation.get("checks"), list) else []
        text = json.dumps(checks, ensure_ascii=False, default=str).casefold()
        return any(marker in text for marker in ["nameerror", "typeerror", "not json serializable", "undefined_names", "unit_test", "runtime_test_mode_guard", "missing_runtime_test_mode_guard", "timeoutexpired", "entrypoint_returned_none_not_dict", "output_is_not_object"])

    def _compact_validation_failure(self, validation: dict[str, Any]) -> dict[str, Any]:
        checks = validation.get("checks") if isinstance(validation.get("checks"), list) else []
        compact_checks: list[dict[str, Any]] = []
        for check in checks[-5:]:
            if not isinstance(check, dict):
                continue
            compact_checks.append({
                "name": check.get("name"),
                "passed": check.get("passed"),
                "status": check.get("status"),
                "reason": check.get("reason"),
                "unknown_imports": check.get("unknown_imports"),
                "undefined_names": check.get("undefined_names"),
                "stderr": str(check.get("stderr") or "")[-1000:],
            })
        return {
            "status": validation.get("status"),
            "reason": validation.get("reason"),
            "checks": compact_checks,
        }


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
        interface_check = self._declared_interface_contract_check(contract=contract, artifact=artifact)
        checks.append(interface_check)
        passed = not missing and not present_forbidden and id_checks_passed and bool(interface_check.get("passed"))
        report = {
            "passed": passed,
            "status": "completed" if passed else "failed",
            "checks": checks,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if tool_dir.exists():
            (tool_dir / "capability_match_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    def _declared_interface_contract_check(self, *, contract: dict[str, Any], artifact: dict[str, Any]) -> dict[str, Any]:
        declared = contract.get("declared_interface") if isinstance(contract.get("declared_interface"), dict) else {}
        if not declared:
            return {"name": "declared_interface_contract", "passed": True, "status": "not_required"}
        tool_dir = Path(str(artifact.get("tool_dir") or ""))
        manifest = artifact.get("manifest") if isinstance(artifact.get("manifest"), dict) else None
        if manifest is None:
            for name in ("manifest.json", "tool.json"):
                path = tool_dir / name
                if path.exists():
                    try:
                        manifest = json.loads(path.read_text(encoding="utf-8") or "{}")
                        break
                    except Exception:
                        manifest = None
        if not isinstance(manifest, dict):
            return {"name": "declared_interface_contract", "passed": False, "reason": "manifest_unavailable"}
        checks: list[dict[str, Any]] = []
        for schema_name in ("input_schema", "connection_schema", "secret_schema"):
            expected = declared.get(schema_name) if isinstance(declared.get(schema_name), dict) else {}
            if not expected:
                continue
            actual = manifest.get(schema_name) if isinstance(manifest.get(schema_name), dict) else {}
            expected_props = set((expected.get("properties") if isinstance(expected.get("properties"), dict) else {}).keys())
            actual_props = set((actual.get("properties") if isinstance(actual.get("properties"), dict) else {}).keys())
            missing = sorted(expected_props - actual_props)
            extra = sorted(actual_props - expected_props) if expected.get("additionalProperties") is False else []
            ok = not missing and not extra
            checks.append({"name": schema_name, "passed": ok, "missing": missing, "extra": extra, "expected": sorted(expected_props), "actual": sorted(actual_props)})
        expected_policy = declared.get("approval_policy") if isinstance(declared.get("approval_policy"), dict) else {}
        if expected_policy:
            actual_policy = manifest.get("approval_policy") if isinstance(manifest.get("approval_policy"), dict) else {}
            if not actual_policy:
                runtime_policy = manifest.get("runtime_execution_policy") if isinstance(manifest.get("runtime_execution_policy"), dict) else {}
                actual_policy = runtime_policy.get("approval_policy") if isinstance(runtime_policy.get("approval_policy"), dict) else {}
            exp_modes = set(expected_policy.get("supported_modes") if isinstance(expected_policy.get("supported_modes"), list) else [])
            act_modes = set(actual_policy.get("supported_modes") if isinstance(actual_policy.get("supported_modes"), list) else actual_policy.get("modes") if isinstance(actual_policy.get("modes"), list) else [])
            exp_default = str(expected_policy.get("default_mode") or "").casefold()
            act_default = str(actual_policy.get("default_mode") or actual_policy.get("default") or "").casefold()
            ok = (not exp_modes or exp_modes.issubset(act_modes)) and (not exp_default or exp_default == act_default)
            checks.append({"name": "approval_policy", "passed": ok, "expected_modes": sorted(exp_modes), "actual_modes": sorted(act_modes), "expected_default": exp_default, "actual_default": act_default})
        failed = [c for c in checks if not c.get("passed")]
        return {"name": "declared_interface_contract", "passed": not failed, "checks": checks, "reason": "declared_interface_mismatch" if failed else ""}

    def _validate_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        tool_dir = Path(str(artifact.get("tool_dir") or ""))
        if not tool_dir.exists():
            return {"passed": False, "status": "failed", "reason": "artifact_directory_missing"}
        checks: list[dict[str, Any]] = []
        py_files = [str(p) for p in tool_dir.rglob("*.py")]
        if py_files:
            proc = self._run_isolated_python(["-m", "py_compile", *py_files], cwd=tool_dir, timeout=30)
            checks.append({
                "name": "python_compile",
                "returncode": proc.get("returncode"),
                "stdout": str(proc.get("stdout") or "")[-2000:],
                "stderr": str(proc.get("stderr") or "")[-2000:],
                "attempts": proc.get("attempts", []),
            })
            if proc.get("returncode") != 0:
                return {"passed": False, "status": "failed", "checks": checks}
        test_candidates: list[Path] = []
        test_dir = Path(str(artifact.get("test_dir") or ""))
        if test_dir.exists():
            test_candidates.extend(sorted(test_dir.glob("test_*.py")))
        legacy_test_file = tool_dir / "test_tool.py"
        if legacy_test_file.exists() and legacy_test_file not in test_candidates:
            test_candidates.append(legacy_test_file)
        test_quality = self._test_static_quality_gate(tool_dir=tool_dir, test_candidates=test_candidates)
        checks.append({"name": "test_static_quality_gate", **test_quality})
        if not test_quality.get("passed"):
            return {
                "passed": False,
                "status": "sandbox_failed",
                "reason": str(test_quality.get("status") or "generated_test_static_quality_failed"),
                "checks": checks,
            }

        sandbox_policy = self._sandbox_validation_execution_policy(tool_dir=tool_dir)
        checks.append({"name": "sandbox_validation_execution_policy", **sandbox_policy})
        if sandbox_policy.get("mode") == "static_only":
            quality = self._artifact_registration_quality_gate(artifact)
            checks.append({"name": "registration_quality_gate", "passed": bool(quality.get("passed")), "result": quality})
            if not quality.get("passed"):
                return {"passed": False, "status": "sandbox_failed", "reason": str(quality.get("reason") or "artifact_quality_gate_failed"), "checks": checks}
            return {
                "passed": True,
                "status": "completed",
                "checks": checks,
                "isolation_level": "static_only",
                "reason": str(sandbox_policy.get("reason") or "external_runtime_requires_live_values"),
            }

        effect_guard = self._effectful_runtime_test_mode_guard(tool_dir=tool_dir)
        checks.append({"name": "effectful_runtime_test_mode_guard", **effect_guard})
        if not effect_guard.get("passed"):
            return {
                "passed": False,
                "status": "sandbox_failed",
                "reason": str(effect_guard.get("reason") or effect_guard.get("status") or "runtime_test_mode_guard_failed"),
                "checks": checks,
            }

        # Only execute validator-owned tests. Generated in-artifact tests are
        # kept as source material but are not authoritative because they may
        # perform live side effects or block. The sandbox-owned contract smoke
        # test is generated from the manifest and verification contract.
        executable_tests = [p for p in test_candidates if test_dir.exists() and self._is_relative_to(p, test_dir)]
        if not executable_tests:
            executable_tests = list(test_candidates)
        for test_file in executable_tests:
            runner = (
                "import runpy, sys; "
                f"sys.path.insert(0, {json.dumps(str(tool_dir))}); "
                f"ns = runpy.run_path({json.dumps(str(test_file))}, run_name='__runtime_test__'); "
                "[fn() for name, fn in sorted(ns.items()) if name.startswith('test_') and callable(fn)]"
            )
            proc = self._run_isolated_python(["-c", runner], cwd=tool_dir, timeout=30)
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
                return {"passed": False, "status": "sandbox_failed", "checks": checks}
        smoke = self._artifact_entrypoint_smoke_test(artifact)
        checks.append({"name": "entrypoint_json_smoke_test", **smoke})
        if not smoke.get("passed"):
            return {"passed": False, "status": "sandbox_failed", "reason": str(smoke.get("reason") or "entrypoint_smoke_test_failed"), "checks": checks}
        quality = self._artifact_registration_quality_gate(artifact)
        checks.append({"name": "registration_quality_gate", "passed": bool(quality.get("passed")), "result": quality})
        if not quality.get("passed"):
            return {"passed": False, "status": "sandbox_failed", "reason": str(quality.get("reason") or "artifact_quality_gate_failed"), "checks": checks}
        return {"passed": True, "status": "completed", "checks": checks, "isolation_level": "clean_subprocess"}

    def _is_relative_to(self, path: Path, parent: Path) -> bool:
        try:
            path.resolve().relative_to(parent.resolve())
            return True
        except Exception:
            return False


    def _sandbox_validation_execution_policy(self, *, tool_dir: Path) -> dict[str, Any]:
        """Decide whether sandbox may execute the generated artifact.

        The decision is generic and schema driven.  Artifacts that require
        preset connection profiles, secret material, or other live external
        values are validated statically in sandbox: syntax, import/name quality,
        manifest/schema contract, and registration quality.  Sandbox must not
        force real credentials, SSL handshakes, account logins, or external
        writes merely to prove code generation.  Artifacts without live external
        dependencies may still run sandbox-owned smoke/unit tests.
        """
        manifest_path = tool_dir / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
        except Exception as exc:
            return {"passed": False, "mode": "unknown", "reason": f"manifest_unreadable:{exc.__class__.__name__}"}

        policy = manifest.get("runtime_execution_policy") if isinstance(manifest.get("runtime_execution_policy"), dict) else {}
        side_effects = str(policy.get("side_effects") or "").strip().casefold()
        safe_effects = {"", "none", "pure", "read_only", "read-only"}
        external_effect = side_effects not in safe_effects

        connection_schema = manifest.get("connection_schema") if isinstance(manifest.get("connection_schema"), dict) else {}
        secret_schema = manifest.get("secret_schema") if isinstance(manifest.get("secret_schema"), dict) else {}
        input_schema = manifest.get("input_schema") if isinstance(manifest.get("input_schema"), dict) else {}
        connection_props = connection_schema.get("properties") if isinstance(connection_schema.get("properties"), dict) else {}
        secret_props = secret_schema.get("properties") if isinstance(secret_schema.get("properties"), dict) else {}
        required_inputs = input_schema.get("required") if isinstance(input_schema.get("required"), list) else []

        source = self._artifact_source_text(tool_dir)
        structural = self._generic_effectful_source_signals(source)
        external_signals = [item for item in structural if item.get("scope") == "external"]
        requires_live_values = bool(connection_props or secret_props)
        requires_runtime_user_values = bool(required_inputs)
        mode = "static_only" if (external_effect or external_signals) and (requires_live_values or requires_runtime_user_values) else "execute_allowed"
        reason = "external_runtime_requires_preset_or_user_values" if mode == "static_only" else "sandbox_owned_execution_allowed"
        return {
            "passed": True,
            "mode": mode,
            "reason": reason,
            "policy_side_effects": side_effects,
            "has_connection_schema": bool(connection_props),
            "has_secret_schema": bool(secret_props),
            "required_input_count": len(required_inputs),
            "external_signal_count": len(external_signals),
        }

    def _artifact_source_text(self, tool_dir: Path) -> str:
        parts: list[str] = []
        for path in sorted(tool_dir.glob("*.py")):
            if path.name.startswith("test_"):
                continue
            try:
                parts.append(path.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue
        return "\n".join(parts)

    def _effectful_runtime_test_mode_guard(self, *, tool_dir: Path) -> dict[str, Any]:
        """Require a local test-mode branch for artifacts declared effectful.

        The guard is driven by runtime policy and generic Python structure, not
        capability names or domain libraries. When an artifact may affect an
        external system or local state, sandbox execution must be able to take a
        local deterministic path before live clients, credentials, or mutations
        are reached.
        """
        manifest_path = tool_dir / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
        except Exception:
            manifest = {}
        policy = manifest.get("runtime_execution_policy") if isinstance(manifest.get("runtime_execution_policy"), dict) else {}
        side_effects = str(policy.get("side_effects") or "").casefold()
        policy_effectful = side_effects not in {"", "none", "pure", "read_only", "read-only"}

        source_parts: list[str] = []
        for path in sorted(tool_dir.glob("*.py")):
            if path.name.startswith("test_"):
                continue
            try:
                source_parts.append(path.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue
        source = "\n".join(source_parts)
        structural = self._generic_effectful_source_signals(source)
        external_signals = [item for item in structural if item.get("scope") == "external"]
        local_signals = [item for item in structural if item.get("scope") == "local_state"]

        # Local runtime persistence is not the same as live external side
        # effects. Capabilities that persist local state, such as timers, must
        # be validated by writing to sandbox-owned storage. Requiring an early
        # dry-run branch before every mkdir/open call would prevent the very
        # persistence behavior that the contract asks the sandbox to verify.
        # This guard therefore requires a test-mode branch only for external or
        # irreversible effects, while still reporting local state signals for
        # auditability.
        local_only_policy_values = {
            "", "none", "pure", "read_only", "read-only",
            "local_state", "local_state_write", "local_write",
            "local_persistence", "filesystem_write", "runtime_storage",
        }
        external_policy = side_effects not in local_only_policy_values
        requires_early_test_branch = bool(external_policy or external_signals)
        if not requires_early_test_branch:
            return {
                "passed": True,
                "status": "local_state_sandbox_allowed" if local_signals else "not_required",
                "policy_side_effects": side_effects,
                "structural_signals": structural,
                "external_signals": external_signals,
                "local_state_signals": local_signals,
            }
        guard = self._generic_test_mode_branch_signal(source)
        passed = bool(guard.get("has_branch") and guard.get("branch_precedes_effectful_signal"))
        return {
            "passed": passed,
            "status": "completed" if passed else "missing_runtime_test_mode_guard",
            "reason": "" if passed else "effectful_runtime_must_have_early_test_mode_branch",
            "policy_side_effects": side_effects,
            "structural_signals": structural,
            "external_signals": external_signals,
            "local_state_signals": local_signals,
            "guard": guard,
        }

    def _generic_effectful_source_signals(self, source: str) -> list[dict[str, Any]]:
        """Return generic effectful-code signals without capability-specific terms."""
        try:
            tree = ast.parse(source or "")
        except SyntaxError:
            return [{"kind": "syntax_unavailable", "line": 0}]
        signals: list[dict[str, Any]] = []
        local_state_method_names = {
            "write", "writelines", "remove", "unlink", "rmdir", "mkdir", "makedirs",
            "replace", "rename",
        }
        external_method_names = {
            "send", "sendall", "sendto", "connect", "request",
            "post", "put", "patch", "delete", "login", "commit", "execute",
        }
        external_constructor_suffixes = {"client", "connection", "session", "transport"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = self._call_name(node.func).casefold()
                last = name.rsplit(".", 1)[-1]
                if last in external_method_names:
                    signals.append({"kind": "effectful_call", "scope": "external", "line": getattr(node, "lineno", 0), "name": last})
                elif last in local_state_method_names:
                    signals.append({"kind": "effectful_call", "scope": "local_state", "line": getattr(node, "lineno", 0), "name": last})
                elif any(last.endswith(suffix) for suffix in external_constructor_suffixes):
                    signals.append({"kind": "external_handle_construction", "scope": "external", "line": getattr(node, "lineno", 0), "name": last})
                elif last == "open" and self._open_call_allows_write(node):
                    signals.append({"kind": "mutable_file_open", "scope": "local_state", "line": getattr(node, "lineno", 0), "name": last})
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                # Importing a module is not itself a side effect. Runtime policy
                # remains the authoritative source for external behavior.
                continue
        return signals[:50]

    def _generic_test_mode_branch_signal(self, source: str) -> dict[str, Any]:
        try:
            tree = ast.parse(source or "")
        except SyntaxError:
            return {"has_branch": False, "branch_precedes_effectful_signal": False, "reason": "syntax_unavailable"}
        branch_lines: list[int] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and self._test_mode_expression(node.test):
                branch_lines.append(getattr(node, "lineno", 0))
        signals = self._generic_effectful_source_signals(source)
        signal_lines = [int(item.get("line") or 0) for item in signals if int(item.get("line") or 0) > 0]
        first_branch = min(branch_lines) if branch_lines else 0
        first_signal = min(signal_lines) if signal_lines else 0
        return {
            "has_branch": bool(first_branch),
            "branch_line": first_branch,
            "first_effectful_line": first_signal,
            "branch_precedes_effectful_signal": bool(first_branch and (not first_signal or first_branch < first_signal)),
        }

    def _test_mode_expression(self, node: ast.AST) -> bool:
        text = ast.unparse(node).casefold() if hasattr(ast, "unparse") else ""
        return any(token in text for token in ["dry_run", "test_mode", "mock"])

    def _call_name(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            prefix = self._call_name(node.value)
            return f"{prefix}.{node.attr}" if prefix else node.attr
        return ""

    def _open_call_allows_write(self, node: ast.Call) -> bool:
        if not node.args and not node.keywords:
            return False
        mode_value = None
        if len(node.args) >= 2:
            mode_value = self._constant_node_value(node.args[1])
        for kw in node.keywords:
            if kw.arg == "mode":
                mode_value = self._constant_node_value(kw.value)
        mode = str(mode_value or "r")
        return any(ch in mode for ch in ["w", "a", "+", "x"])

    def _constant_node_value(self, node: ast.AST) -> Any:
        """Return a literal AST value without evaluating runtime expressions.

        This helper is intentionally generic. It is used by static quality gates
        that inspect generated Python code. It does not contain capability names,
        provider names, or domain-specific behavior.
        """
        if isinstance(node, ast.Constant):
            return node.value
        if hasattr(ast, "Index") and isinstance(node, ast.Index):
            return self._constant_node_value(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = self._constant_node_value(node.operand)
            if isinstance(value, (int, float)):
                return value if isinstance(node.op, ast.UAdd) else -value
        return None

    def _test_static_quality_gate(self, *, tool_dir: Path, test_candidates: list[Path]) -> dict[str, Any]:
        local_modules = {path.stem for path in tool_dir.rglob("*.py")}
        declared_imports = self._manifest_dependency_imports(tool_dir)
        unknown: list[dict[str, str]] = []
        undefined: list[dict[str, str]] = []
        for test_file in test_candidates:
            try:
                tree = ast.parse(test_file.read_text(encoding="utf-8"))
            except SyntaxError as exc:
                return {
                    "passed": False,
                    "status": "syntax_error",
                    "test_file": str(test_file),
                    "error": str(exc),
                }
            for module in self._top_level_imports(tree):
                if module in local_modules or module in declared_imports or module in getattr(sys, "stdlib_module_names", set()):
                    continue
                unknown.append({"test_file": str(test_file), "module": module})
            for name in self._undefined_loaded_names(tree):
                undefined.append({"test_file": str(test_file), "name": name})
        status = "completed"
        if unknown:
            status = "undeclared_external_test_dependencies"
        elif undefined:
            status = "generated_test_undefined_names"
        return {
            "passed": not unknown and not undefined,
            "status": status,
            "unknown_imports": unknown,
            "undefined_names": undefined,
        }

    def _undefined_loaded_names(self, tree: ast.AST) -> list[str]:
        defined: set[str] = {"__name__", "True", "False", "None"}
        try:
            import builtins
            defined.update(name for name in dir(builtins) if isinstance(name, str))
        except Exception:
            pass
        loaded: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    defined.add(str(alias.asname or alias.name).split(".", 1)[0])
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    defined.add(str(alias.asname or alias.name))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defined.add(str(node.name))
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
                        defined.add(str(arg.arg))
                    if node.args.vararg:
                        defined.add(str(node.args.vararg.arg))
                    if node.args.kwarg:
                        defined.add(str(node.args.kwarg.arg))
            elif isinstance(node, ast.Name):
                if isinstance(node.ctx, ast.Store):
                    defined.add(str(node.id))
                elif isinstance(node.ctx, ast.Load):
                    loaded.add(str(node.id))
            elif isinstance(node, ast.ExceptHandler) and node.name:
                defined.add(str(node.name))
        return sorted(name for name in loaded if name not in defined and not name.startswith("__"))

    def _top_level_imports(self, tree: ast.AST) -> list[str]:
        modules: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(str(alias.name or "").split(".", 1)[0] for alias in node.names if alias.name)
            elif isinstance(node, ast.ImportFrom):
                if getattr(node, "level", 0):
                    continue
                module = str(node.module or "").split(".", 1)[0]
                if module:
                    modules.append(module)
        return modules

    def _manifest_dependency_imports(self, tool_dir: Path) -> set[str]:
        manifest_path = tool_dir / "manifest.json"
        if not manifest_path.exists():
            return set()
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return set()
        dependencies = manifest.get("dependencies") if isinstance(manifest, dict) else []
        return self._dependency_import_names(self._normalized_dependencies(dependencies))

    def _artifact_entrypoint_smoke_test(self, artifact: dict[str, Any]) -> dict[str, Any]:
        tool_dir = Path(str(artifact.get("tool_dir") or ""))
        manifest_path = Path(str(artifact.get("manifest_path") or tool_dir / "manifest.json"))
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return {"passed": False, "status": "failed", "reason": "manifest_unreadable", "error": str(exc)[:500]}
        entrypoint = manifest.get("entrypoint") if isinstance(manifest.get("entrypoint"), dict) else {}
        module_path = tool_dir / str(entrypoint.get("module") or "tool.py")
        function_name = str(entrypoint.get("function") or "run")
        verification_input = manifest.get("verification_input") if isinstance(manifest.get("verification_input"), dict) else {}
        if not module_path.exists():
            return {"passed": False, "status": "failed", "reason": "implementation_module_missing", "module_path": str(module_path)}

        smoke_id = f"runtime_capability_smoke_{tool_dir.name}_{os.getpid()}_{int(datetime.now(timezone.utc).timestamp() * 1000)}"
        smoke_output_path = Path(tempfile.gettempdir()) / f"{smoke_id}.json"
        smoke_runner_path = Path(tempfile.gettempdir()) / f"{smoke_id}.py"
        smoke_runner_source = "\n".join([
            "import importlib.util, json, pathlib, sys, traceback",
            f"module_path = {json.dumps(str(module_path))}",
            f"function_name = {json.dumps(function_name)}",
            f"payload = json.loads({json.dumps(json.dumps(verification_input, ensure_ascii=False))})",
            f"output_path = pathlib.Path({json.dumps(str(smoke_output_path))})",
            "try:",
            "    spec = importlib.util.spec_from_file_location('runtime_generated_smoke_tool', module_path)",
            "    if spec is None or spec.loader is None:",
            "        raise RuntimeError('entrypoint_spec_not_loadable')",
            "    module = importlib.util.module_from_spec(spec)",
            "    spec.loader.exec_module(module)",
            "    output = getattr(module, function_name)(payload)",
            "    encoded = json.dumps(output, ensure_ascii=False)",
            "    output_path.write_text(encoded, encoding='utf-8')",
            "    sys.stdout.write(encoded + '\\n')",
            "    sys.stdout.flush()",
            "except Exception as exc:",
            "    error_payload = {'status': 'failed', 'error_type': exc.__class__.__name__, 'error': str(exc), 'traceback': traceback.format_exc()[-4000:]}",
            "    output_path.write_text(json.dumps(error_payload, ensure_ascii=False), encoding='utf-8')",
            "    sys.stdout.write(json.dumps(error_payload, ensure_ascii=False) + '\\n')",
            "    sys.stdout.flush()",
            "    raise",
        ])
        smoke_runner_path.write_text(smoke_runner_source, encoding="utf-8")
        proc = self._run_isolated_python([str(smoke_runner_path)], cwd=tool_dir, timeout=30)
        output: Any = None
        parse_error = ""
        stdout = str(proc.get("stdout") or "")
        if proc.get("returncode") == 0:
            try:
                output = self._parse_json_from_subprocess_stdout(stdout)
            except Exception as stdout_exc:
                try:
                    sidecar_text = smoke_output_path.read_text(encoding="utf-8")
                    output = json.loads(sidecar_text)
                except Exception as file_exc:
                    parse_error = (
                        f"output_json_parse_failed:{stdout_exc.__class__.__name__};"
                        f"sidecar_failed:{file_exc.__class__.__name__};"
                        f"sidecar_exists:{smoke_output_path.exists()};"
                        f"sidecar_size:{smoke_output_path.stat().st_size if smoke_output_path.exists() else 0}"
                    )
        try:
            smoke_output_path.unlink(missing_ok=True)
            smoke_runner_path.unlink(missing_ok=True)
        except Exception:
            pass

        expectations = manifest.get("verification_expectations") if isinstance(manifest.get("verification_expectations"), dict) else {}
        contract = self._runtime_output_contract_checks(
            verification_input=verification_input,
            output=output,
            expectations=expectations,
            manifest=manifest if isinstance(manifest, dict) else {},
        )
        passed = proc.get("returncode") == 0 and not parse_error and bool(contract.get("passed"))
        return {
            "passed": passed,
            "status": "completed" if passed else "failed",
            "reason": "" if passed else (parse_error or str(contract.get("reason") or "runtime_output_contract_failed") or "entrypoint_output_not_json_serializable_or_execution_failed"),
            "returncode": proc.get("returncode"),
            "stdout": stdout[-2000:],
            "stderr": str(proc.get("stderr") or "")[-2000:],
            "attempts": proc.get("attempts", []),
            "contract": contract,
        }

    def _artifact_registration_quality_gate(self, artifact: dict[str, Any]) -> dict[str, Any]:
        """Reject blueprint/stub artifacts before registration.

        The gate is strict because a registry entry means a real runtime tool is
        available.  Blueprint-only artifacts can still be saved under
        runtime/generated, but they must not appear as registered tools.
        """
        tool_dir = Path(str(artifact.get("tool_dir") or ""))
        manifest_path = Path(str(artifact.get("manifest_path") or tool_dir / "manifest.json"))
        checks: list[dict[str, Any]] = []
        if not manifest_path.exists():
            return {"passed": False, "status": "not_registered", "reason": "manifest_missing", "checks": checks}
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return {"passed": False, "status": "not_registered", "reason": f"manifest_unreadable:{exc.__class__.__name__}", "checks": checks}

        if str(manifest.get("artifact_kind") or "") == "blueprint_only_not_registerable":
            checks.append({"name": "artifact_kind", "passed": False, "actual": manifest.get("artifact_kind")})
            return {"passed": False, "status": "not_registered", "reason": "blueprint_artifact_is_not_registerable", "checks": checks}
        checks.append({"name": "artifact_kind", "passed": True, "actual": manifest.get("artifact_kind")})

        for schema_name in ["input_schema", "connection_schema", "secret_schema"]:
            schema = manifest.get(schema_name) if isinstance(manifest.get(schema_name), dict) else {}
            schema_check = self._schema_is_specific(schema)
            checks.append({"name": schema_name, **schema_check})
            if not schema_check.get("passed"):
                return {"passed": False, "status": "not_registered", "reason": f"{schema_name}_is_empty_or_open", "checks": checks}

        entrypoint = manifest.get("entrypoint") if isinstance(manifest.get("entrypoint"), dict) else {}
        module_path = tool_dir / str(entrypoint.get("module") or "tool.py")
        function_name = str(entrypoint.get("function") or "run")
        entrypoint_check = self._entrypoint_source_check(module_path=module_path, function_name=function_name)
        checks.append({"name": "entrypoint_callable_contract", **entrypoint_check})
        if not entrypoint_check.get("passed"):
            return {"passed": False, "status": "not_registered", "reason": str(entrypoint_check.get("reason") or "entrypoint_not_callable"), "checks": checks}

        text = self._artifact_source_text(tool_dir)
        forbidden = ["requires_runtime_implementation", "runtime blueprint artifact verified", "blueprint only; not a registerable"]
        present_forbidden = [item for item in forbidden if item in text.casefold()]
        checks.append({"name": "no_stub_markers", "passed": not present_forbidden, "present": present_forbidden})
        if present_forbidden:
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

    def _entrypoint_source_check(self, *, module_path: Path, function_name: str) -> dict[str, Any]:
        if not module_path.exists():
            return {"passed": False, "reason": "entrypoint_module_missing", "module_path": str(module_path)}
        try:
            source = module_path.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(source or "")
        except SyntaxError as exc:
            return {"passed": False, "reason": "entrypoint_source_syntax_error", "error": str(exc)[:500]}
        except Exception as exc:
            return {"passed": False, "reason": "entrypoint_source_unreadable", "error_type": exc.__class__.__name__}
        functions = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        fn = functions.get(function_name)
        if not fn:
            return {"passed": False, "reason": "entrypoint_function_missing", "expected_function": function_name, "available_functions": sorted(functions)}
        args = list(fn.args.posonlyargs) + list(fn.args.args)
        if len(args) != 1:
            return {"passed": False, "reason": "entrypoint_must_accept_one_payload", "expected_function": function_name, "argument_count": len(args)}
        return {"passed": True, "expected_function": function_name, "argument": args[0].arg}

    def _schema_is_specific(self, schema: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(schema, dict) or schema.get("type") != "object":
            return {"passed": False, "reason": "schema_is_not_object"}
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        if not properties:
            if schema.get("additionalProperties") is False and bool(schema.get("x-empty-schema-allowed")):
                return {"passed": True, "property_count": 0, "required": schema.get("required", []), "empty_schema_allowed": True}
            return {"passed": False, "reason": "schema_has_no_properties"}
        if schema.get("additionalProperties") is True and len(properties) == 0:
            return {"passed": False, "reason": "schema_accepts_anything"}
        if schema.get("additionalProperties") is True and not schema.get("required"):
            return {"passed": False, "reason": "schema_is_too_open"}
        return {"passed": True, "property_count": len(properties), "required": schema.get("required", [])}

    def _artifact_source_text(self, tool_dir: Path) -> str:
        parts: list[str] = []
        if not tool_dir.exists():
            return ""
        for path in sorted(tool_dir.rglob("*")):
            if path.is_file() and path.suffix.lower() in {".py", ".json", ".md", ".txt", ".yaml", ".yml"}:
                try:
                    parts.append(path.read_text(encoding="utf-8", errors="ignore"))
                except Exception:
                    continue
        return "\n".join(parts)

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
            try:
                json.dumps(output, ensure_ascii=False)
            except TypeError as exc:
                report = {
                    "passed": False,
                    "status": "failed",
                    "reason": "output_not_json_serializable",
                    "error": str(exc)[:2000],
                    "input": verification_input,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                self._write_verification_report(artifact, report)
                return report
            expectations = template.get("verification_expectations") if isinstance(template.get("verification_expectations"), dict) else {}
            manifest = dict(template)
            manifest.setdefault("input_schema", template.get("input_schema") if isinstance(template.get("input_schema"), dict) else {})
            manifest.setdefault("output_schema", template.get("output_schema") if isinstance(template.get("output_schema"), dict) else {})
            expectation_passed = self._matches_expectations(output, expectations)
            contract = self._runtime_output_contract_checks(
                verification_input=verification_input,
                output=output,
                expectations=expectations,
                manifest=manifest,
            )
            passed = bool(expectation_passed and contract.get("passed"))
            report = {
                "passed": passed,
                "status": "completed" if passed else "failed",
                "reason": "" if passed else str(contract.get("reason") or "verification_contract_failed"),
                "input": verification_input,
                "output": output,
                "expectations": expectations,
                "expectation_passed": expectation_passed,
                "contract": contract,
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


    def _parse_json_from_subprocess_stdout(self, stdout: str) -> Any:
        """Parse the JSON payload printed by an isolated smoke runner.

        Some local Python/debug environments can write advisory text around the
        runner output.  The runner contract is therefore: the generated tool
        returns a JSON-serializable object, and the smoke runner prints that
        object as a JSON line.  We parse the last valid JSON-looking line rather
        than treating unrelated diagnostics as tool output.
        """
        text = str(stdout or "").strip()
        if not text:
            raise ValueError("empty_stdout")
        try:
            return json.loads(text)
        except Exception:
            pass
        for line in reversed(text.splitlines()):
            candidate = line.strip()
            if not candidate or candidate[0] not in '[{"':
                continue
            try:
                return json.loads(candidate)
            except Exception:
                continue
        raise ValueError("no_json_payload_in_stdout")

    def _runtime_output_contract_checks(
        self,
        *,
        verification_input: dict[str, Any],
        output: Any,
        expectations: dict[str, Any],
        manifest: dict[str, Any],
    ) -> dict[str, Any]:
        """Generic execution-quality checks for generated runtime tools.

        Unit tests and smoke tests prove that code can run.  This guard checks
        that the returned payload is not merely a copied prompt, format string,
        or placeholder.  The rules are schema/contract driven and do not encode
        a concrete business capability.
        """
        checks: list[dict[str, Any]] = []
        if not isinstance(output, dict):
            return {"passed": False, "reason": "output_is_not_object", "checks": checks}

        output_schema = manifest.get("output_schema") if isinstance(manifest.get("output_schema"), dict) else {}
        expected_fields = self._declared_output_fields(output_schema=output_schema, expectations=expectations)
        flattened_output = self._flatten_object(output)
        flattened_input = self._flatten_object(verification_input)

        missing = [field for field in expected_fields if not self._has_nested_key(output, field)]
        checks.append({"name": "declared_output_fields_present", "passed": not missing, "missing": missing, "fields": expected_fields})
        if missing:
            return {"passed": False, "reason": "declared_output_fields_missing", "checks": checks}

        copied_dynamic_values: list[dict[str, str]] = []
        input_format_values: list[tuple[str, str]] = []
        for key, value in flattened_input.items():
            if isinstance(value, str) and self._looks_like_format_or_template(value, key):
                input_format_values.append((key, value))
        for out_key, out_value in flattened_output.items():
            if not isinstance(out_value, str):
                continue
            stripped_output = out_value.strip()
            for in_key, in_value in input_format_values:
                if stripped_output and stripped_output.casefold() == in_value.strip().casefold():
                    copied_dynamic_values.append({"output_key": out_key, "input_key": in_key, "copied_value": stripped_output[:200]})
        checks.append({"name": "dynamic_output_not_copied_from_format_or_template", "passed": not copied_dynamic_values, "copied": copied_dynamic_values})
        if copied_dynamic_values:
            return {"passed": False, "reason": "output_copied_format_or_template_instead_of_runtime_value", "checks": checks}

        placeholder_values: list[dict[str, str]] = []
        for out_key, out_value in flattened_output.items():
            if isinstance(out_value, str) and self._looks_like_unresolved_placeholder(out_value):
                placeholder_values.append({"output_key": out_key, "value": out_value[:200]})
        checks.append({"name": "no_unresolved_placeholder_output", "passed": not placeholder_values, "placeholders": placeholder_values})
        if placeholder_values:
            return {"passed": False, "reason": "unresolved_placeholder_output", "checks": checks}

        specification_checks = self._specification_contract_checks(
            output=output,
            flattened_output=flattened_output,
            manifest=manifest,
        )
        checks.append(specification_checks)
        if not specification_checks.get("passed"):
            return {"passed": False, "reason": str(specification_checks.get("reason") or "specification_contract_failed"), "checks": checks}

        return {"passed": True, "checks": checks}

    def _declared_output_fields(self, *, output_schema: dict[str, Any], expectations: dict[str, Any]) -> list[str]:
        """Return output fields that must be present in a smoke-test response.

        A JSON schema property is not required merely because it is declared in
        ``properties``.  Some generated capabilities legitimately return
        ``{"status": "completed"}`` for mutation-style operations while
        returning an optional ``data`` object for read/list operations.

        Therefore this method is contract-driven:
        - require only fields listed in the schema's top-level ``required``;
        - require explicit verification expectation keys;
        - do not promote optional properties into mandatory smoke-test fields.

        Nested field requirements remain handled by the specification contract
        checks when the corresponding parent object is required or present.
        """
        fields: list[str] = []
        required = output_schema.get("required") if isinstance(output_schema.get("required"), list) else []
        for name in required:
            if isinstance(name, str) and name not in fields:
                fields.append(name)
        for name in expectations.keys():
            if isinstance(name, str) and name != "status" and name not in fields:
                fields.append(name)
        return fields

    def _flatten_object(self, value: Any, prefix: str = "") -> dict[str, Any]:
        flattened: dict[str, Any] = {}
        if isinstance(value, dict):
            for key, child in value.items():
                child_key = f"{prefix}.{key}" if prefix else str(key)
                flattened.update(self._flatten_object(child, child_key))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                child_key = f"{prefix}[{index}]" if prefix else f"[{index}]"
                flattened.update(self._flatten_object(child, child_key))
        else:
            flattened[prefix] = value
        return flattened

    def _has_nested_key(self, output: dict[str, Any], key: str) -> bool:
        if key in output:
            return True
        data = output.get("data") if isinstance(output.get("data"), dict) else {}
        return key in data

    def _looks_like_format_or_template(self, value: str, key: str = "") -> bool:
        text = str(value or "").strip()
        lowered_key = str(key or "").casefold()
        if "format" in lowered_key or "template" in lowered_key:
            return True
        # Common date/time format tokens across user-facing and Python styles.
        return bool(re.search(r"(%[YymdHMSzZ]|Y{2,4}|M{2}|D{2}|H{2}|h{2}|m{2}|s{2}|ISO-?8601)", text, flags=re.I))

    def _looks_like_unresolved_placeholder(self, value: str) -> bool:
        text = str(value or "").strip()
        if re.search(r"\{\{[^{}]+\}\}|<[^<>]+>|\$\{[^{}]+\}", text):
            return True
        # Pure alphabetic separator templates are unresolved placeholders when
        # they contain no runtime data. This check is generic and does not map
        # formats or repair generated outputs.
        if text and not re.search(r"\d", text) and re.search(r"[-_:/ ]", text):
            compact = re.sub(r"[^A-Za-z]", "", text)
            if compact and len(set(compact)) <= 4 and any(ch in compact for ch in "YyMDdHhmsS"):
                return True
        return False

    def _specification_contract_checks(self, *, output: dict[str, Any], flattened_output: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
        specification = manifest.get("specification_contract") if isinstance(manifest.get("specification_contract"), dict) else {}
        verification_contract = specification.get("verification_contract") if isinstance(specification.get("verification_contract"), dict) else {}
        if not verification_contract:
            return {"name": "specification_contract", "passed": True, "reason": "no_specification_contract"}

        output_contracts = verification_contract.get("output_contracts") if isinstance(verification_contract.get("output_contracts"), list) else []
        missing_required: list[str] = []
        for item in output_contracts:
            if not isinstance(item, dict) or not item.get("required"):
                continue
            path = str(item.get("path") or "")
            if path and not self._has_contract_path(output, path):
                missing_required.append(path)
        if missing_required:
            return {"name": "specification_contract", "passed": False, "reason": "required_contract_outputs_missing", "missing": missing_required}

        bindings = verification_contract.get("output_bindings") if isinstance(verification_contract.get("output_bindings"), list) else []
        copied: list[dict[str, str]] = []
        for item in bindings:
            if not isinstance(item, dict):
                continue
            output_path = str(item.get("output_path") or "")
            source_path = str(item.get("source_path") or "")
            source_value = self._get_nested_value(verification_contract.get("verification_input"), source_path.replace("input.", ""))
            output_value = self._get_contract_output_value(output, output_path)
            if isinstance(source_value, str) and isinstance(output_value, str) and source_value.strip() and output_value.strip().casefold() == source_value.strip().casefold():
                copied.append({"output_path": output_path, "source_path": source_path, "copied_value": output_value[:200]})
        if copied:
            return {"name": "specification_contract", "passed": False, "reason": "output_copied_declared_format_or_template", "copied": copied}

        type_failures: list[dict[str, str]] = []
        for item in output_contracts:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "")
            expected_type = str(item.get("json_type") or "").casefold()
            if not path or not expected_type:
                continue
            value = self._get_contract_output_value(output, path)
            if value is None:
                continue
            if not self._json_type_matches(value, expected_type):
                type_failures.append({"path": path, "expected_type": expected_type, "actual_type": type(value).__name__})
        if type_failures:
            return {"name": "specification_contract", "passed": False, "reason": "output_type_contract_failed", "failures": type_failures}

        return {"name": "specification_contract", "passed": True, "bindings_checked": len(bindings), "output_contract_count": len(output_contracts)}

    def _has_contract_path(self, output: dict[str, Any], contract_path: str) -> bool:
        sentinel = object()
        return self._get_contract_output_value(output, contract_path, default=sentinel) is not sentinel

    def _get_contract_output_value(self, output: dict[str, Any], contract_path: str, default: Any = None) -> Any:
        path = str(contract_path or "")
        if path.startswith("output."):
            path = path[len("output."):]
        value = self._get_nested_value(output, path, default=default)
        if value is not default:
            return value
        data = output.get("data") if isinstance(output, dict) and isinstance(output.get("data"), dict) else None
        if data is not None:
            if path.startswith("data."):
                return self._get_nested_value(output, path, default=default)
            return self._get_nested_value(data, path, default=default)
        return default

    def _get_nested_value(self, value: Any, path: str, default: Any = None) -> Any:
        current = value
        for part in [p for p in str(path or "").split(".") if p]:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return default
        return current

    def _json_type_matches(self, value: Any, expected_type: str) -> bool:
        if expected_type in {"", "any"}:
            return True
        if expected_type == "string":
            return isinstance(value, str)
        if expected_type in {"number", "integer"}:
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if expected_type == "boolean":
            return isinstance(value, bool)
        if expected_type == "object":
            return isinstance(value, dict)
        if expected_type == "array":
            return isinstance(value, list)
        if expected_type == "null":
            return value is None
        return True

    def _matches_expectations(self, output: Any, expectations: dict[str, Any]) -> bool:
        success_statuses = {"completed", "success", "ok", "executed", "passed", ""}
        if not expectations:
            return isinstance(output, dict) and str(output.get("status") or "").lower() in success_statuses
        if not isinstance(output, dict):
            return False
        for key, expected in expectations.items():
            actual = output.get(key)
            if key == "status":
                expected_status = str(expected or "").strip().lower()
                actual_status = str(actual or "").strip().lower()
                if expected_status in success_statuses and actual_status in success_statuses:
                    continue
            if actual != expected:
                data = output.get("data") if isinstance(output.get("data"), dict) else {}
                data_actual = data.get(key)
                if data_actual == expected:
                    continue
                # Verification examples are sample values used to exercise the generated
                # artifact.  For non-status fields, do not require exact equality unless
                # the expectation explicitly declares an equality contract.  Dynamic
                # runtime outputs must be validated by schema/contract checks instead
                # of being compared against a copied sample value.
                if self._expectation_requires_exact_match(expected):
                    return False
                if actual is None and data_actual is None:
                    return False
                continue
        return True

    def _expectation_requires_exact_match(self, expected: Any) -> bool:
        if isinstance(expected, dict):
            return any(key in expected for key in ("const", "equals", "exact", "expected_value"))
        return False

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
        # Final registry guard: this check runs immediately before writing
        # registry files.  Even if an earlier validator is bypassed, blueprint,
        # stub, open-schema, or unverified artifacts cannot become enabled tools.
        final_quality = self._artifact_registration_quality_gate(artifact)
        final_checks = [
            {"name": "validation_passed", "passed": bool(validation.get("passed")), "result": validation},
            {"name": "verification_passed", "passed": bool(verification_run.get("passed")), "result": verification_run},
            {"name": "registration_gate_safe", "passed": bool((acquisition_gate or {}).get("safe_to_register")), "result": acquisition_gate or {}},
            {"name": "final_artifact_quality", "passed": bool(final_quality.get("passed")), "result": final_quality},
        ]
        if not all(bool(item.get("passed")) for item in final_checks):
            report = {
                "status": "not_registered",
                "reason": "final_registration_guard_blocked",
                "checks": final_checks,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            tool_dir = Path(str(artifact.get("tool_dir") or ""))
            if tool_dir.exists():
                (tool_dir / "registration_blocked_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            return report

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

    def _build_live_verification_interaction_request(self, *, registration: dict[str, Any], run_id: str = "", session_id: str = "") -> dict[str, Any] | None:
        """Ask Agent Studio for real runtime values after sandbox registration.

        This is intentionally schema-driven.  The acquisition layer does not know
        the meaning of any capability field; it only exposes declared input,
        connection, and secret schemas so the user can perform a live verification
        run after the safe sandbox/mock checks have passed.
        """
        tool_record = registration.get("tool_record") if isinstance(registration.get("tool_record"), dict) else {}
        tool_id = str(tool_record.get("tool_id") or "").strip()
        if not tool_id:
            return None
        connection_schema = tool_record.get("connection_schema") if isinstance(tool_record.get("connection_schema"), dict) else {}
        secret_schema = tool_record.get("secret_schema") if isinstance(tool_record.get("secret_schema"), dict) else {}
        input_schema = tool_record.get("input_schema") if isinstance(tool_record.get("input_schema"), dict) else {}
        side_effects = tool_record.get("runtime_execution_policy") if isinstance(tool_record.get("runtime_execution_policy"), dict) else {}
        should_offer_live_verify = bool(connection_schema.get("properties") or secret_schema.get("properties"))
        if not should_offer_live_verify and str(side_effects.get("side_effects") or "").strip().lower() not in {"yes", "true", "external", "side_effects", "runtime_declared"}:
            return None

        fields: list[dict[str, Any]] = []
        fields.extend(self._interaction_fields_from_schema(schema=connection_schema, scope="connection", tool_id=tool_id))
        fields.extend(self._interaction_fields_from_schema(schema=secret_schema, scope="secrets", tool_id=tool_id, force_password=True))
        fields.extend(self._interaction_fields_from_schema(schema=input_schema, scope="input", tool_id=tool_id))
        if not fields:
            return None
        request = {
            "type": "runtime_tool_live_verification",
            "kind": "runtime_tool_live_verification",
            "tool_id": tool_id,
            "capability_id": tool_id,
            "source_run_id": run_id,
            "session_id": session_id,
            "profile_id": "default",
            "message": "Provide runtime connection, secret, and sample input values to run a live verification after sandbox registration.",
            "fields": fields,
            "approval_confirmed": True,
        }
        scoped = capability_scoped_state_store.record_interaction(
            session_id=session_id or "default_session",
            run_id=run_id or tool_id,
            capability_id=tool_id,
            interaction_type="runtime_tool_live_verification",
            request=request,
        )
        return scoped.get("request") if isinstance(scoped, dict) else request

    def _interaction_fields_from_schema(self, *, schema: dict[str, Any], scope: str, tool_id: str, force_password: bool = False) -> list[dict[str, Any]]:
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        required = {str(x) for x in schema.get("required", [])} if isinstance(schema.get("required"), list) else set()
        fields: list[dict[str, Any]] = []
        for name, spec in properties.items():
            key = str(name or "").strip()
            if not key:
                continue
            prop = spec if isinstance(spec, dict) else {}
            json_type = str(prop.get("type") or "string").lower()
            if force_password:
                input_type = "password"
            elif json_type == "array":
                input_type = "list"
            elif json_type == "boolean":
                input_type = "boolean"
            elif json_type in {"number", "integer"}:
                input_type = "number"
            else:
                input_type = "textarea" if "body" in key.casefold() else "text"
            fields.append({
                "kind": "runtime_tool_live_verification",
                "tool_id": tool_id,
                "profile_id": "default",
                "scope": scope,
                "parameter_name": key,
                "field": f"{scope}.{key}",
                "label": str(prop.get("title") or key.replace("_", " ")),
                "message": str(prop.get("description") or f"Provide {scope} value for {key}."),
                "input_type": input_type,
                "required": key in required,
            })
        return fields

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
