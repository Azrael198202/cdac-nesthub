from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from ai_core.model_orchestration import LiteLLMBrainClient
from presentation_brain.profile_registry import PresentationProfileRegistry


@dataclass
class FailureUserMessage:
    """Human-readable failure explanation produced by Presentation Brain.

    The message is generated from generic failure classes plus evidence.  It is
    intentionally not domain-specific: no capability, agent, or business terms
    are hard-coded.  Deterministic templates are used first; LLM explanation is
    only an upgrade path for unknown, ambiguous, or multi-failure situations.
    """

    title: str
    summary: str
    reasons: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    location: list[str] = field(default_factory=list)
    severity: str = "error"
    source: str = "presentation_brain.deterministic_renderer"
    llm_used: bool = False
    technical: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FailureMessageRenderer:
    """Render structured failure reports into user-facing messages.

    Design:
    1. Failure class and evidence are produced by Verification/Repair layers.
    2. Presentation Brain maps those generic classes to stable wording.
    3. When the report is unknown, ambiguous, or has many interacting failures,
       the renderer may upgrade to LLM through BrainModelRouter/LiteLLM.

    This avoids maintaining thousands of hand-written error messages while also
    avoiding an LLM call for deterministic cases such as missing step references.
    """

    TEMPLATE_LIBRARY: dict[str, dict[str, Any]] = {
        "task_graph_static_validation_failed": {
            "title": "Task graph creation failed",
            "summary": "The task could not be converted into a safe executable graph.",
            "suggestions": [
                "Review the highlighted references in the task instruction.",
                "Use existing step numbers, participant names, and parameter blocks.",
                "Create or select the missing participant before referencing it.",
            ],
        },
        "agent_reference_not_found": {
            "title": "Participant reference not found",
            "summary": "The task references a participant that does not exist or is not available in the current runtime catalog.",
            "suggestions": [
                "Use an existing participant name exactly as registered.",
                "Create the missing participant first, then create the task again.",
            ],
        },
        "agent_reference_ambiguous": {
            "title": "Participant reference is ambiguous",
            "summary": "The task reference is close to one or more existing participants, but it is not an exact safe match.",
            "suggestions": [
                "Choose one of the suggested existing participants.",
                "Rewrite the task instruction with the exact participant name.",
            ],
        },
        "template_reference_not_found": {
            "title": "Template reference not found",
            "summary": "The task uses a template variable that points to a step or result that does not exist in the task graph.",
            "suggestions": [
                "Replace the template variable with an existing step result.",
                "Add the missing upstream step before using its result.",
            ],
        },
        "template_resolution_problem": {
            "title": "Template value was not resolved",
            "summary": "A placeholder remained unresolved when the runtime tried to produce or deliver the result.",
            "suggestions": [
                "Check the referenced step, participant, or output field.",
                "Make sure the upstream result exists before it is used downstream.",
            ],
        },
        "schema_contract_problem": {
            "title": "Schema contract validation failed",
            "summary": "A runtime input or output did not match the declared structural contract.",
            "suggestions": [
                "Check required fields and value types.",
                "Update the parameter mapping or result normalization logic.",
            ],
        },
        "dependency_mapping_problem": {
            "title": "Dependency mapping failed",
            "summary": "A downstream step could not safely use the expected upstream result.",
            "suggestions": [
                "Check the dependency graph and referenced source step.",
                "Ensure the upstream participant completed with a usable result.",
            ],
        },
        "parameter_binding_problem": {
            "title": "Required input was not bound",
            "summary": "The runtime could not find a required value even though the task may have described it.",
            "suggestions": [
                "Check the parameter block and participant name it belongs to.",
                "Ensure the runtime parameter key matches the participant contract.",
            ],
        },
        "capability_execution_problem": {
            "title": "Capability execution did not match the plan",
            "summary": "A participant did not execute the capability or runtime operation that the task graph expected.",
            "suggestions": [
                "Check participant-to-capability binding.",
                "Check registered tool dispatch and execution lock behavior.",
            ],
        },
        "expectation_mismatch_problem": {
            "title": "Result did not satisfy the task expectation",
            "summary": "The runtime completed structurally, but the produced result does not appear to satisfy the requested outcome.",
            "suggestions": [
                "Review the expected outcome and actual result material.",
                "Use the verification report to decide whether the task, graph, or capability should be revised.",
            ],
        },
        "side_effect_verification_problem": {
            "title": "External effect could not be fully verified",
            "summary": "The runtime accepted or completed an external action, but its real-world effect was not fully confirmed.",
            "suggestions": [
                "If the external result did not occur, submit user feedback so repair can start.",
                "Add a read-back or status-check verifier for this capability when possible.",
            ],
        },
        "user_confirmed_side_effect_failure": {
            "title": "User confirmed the external effect failed",
            "summary": "The user reported that an external side effect did not actually work after the runtime accepted it.",
            "suggestions": [
                "Start repair using the related confirmation record and runtime evidence.",
                "Check the capability implementation and external operation adapter.",
            ],
        },
        "runtime_artifact_lookup_problem": {
            "title": "Runtime artifact could not be found",
            "summary": "The runtime referenced a task, graph, plan, or generated artifact that was not available.",
            "suggestions": [
                "Rebuild the task graph or select the latest active revision.",
                "Check runtime generated artifact paths and revision metadata.",
            ],
        },
        "execution_verification_problem": {
            "title": "Execution verification failed",
            "summary": "The runtime result did not pass generic verification checks.",
            "suggestions": [
                "Inspect the failed checks and evidence package.",
                "Classify the failure further before changing code.",
            ],
        },
        "unknown_problem": {
            "title": "Runtime problem detected",
            "summary": "The runtime detected a failure, but it could not classify it with high confidence.",
            "suggestions": [
                "Inspect the evidence package and runtime traces.",
                "Escalate to repair analysis if the problem repeats.",
            ],
        },
    }

    def __init__(self, *, llm_client: LiteLLMBrainClient | None = None) -> None:
        self.llm = llm_client or LiteLLMBrainClient()

    def render(self, report: dict[str, Any], *, allow_llm: bool = True, profile: str | None = None) -> FailureUserMessage:
        report = report if isinstance(report, dict) else {}
        failed_checks = report.get("failed_checks") if isinstance(report.get("failed_checks"), list) else []
        failed_checks = self._dedupe_checks(failed_checks)
        failure_class = str(report.get("failure_class") or self._infer_primary_failure_class(failed_checks) or "unknown_problem")
        profile_obj = PresentationProfileRegistry.get(profile)
        message = self._render_deterministic(report=report, failure_class=failure_class, failed_checks=failed_checks)
        effective_allow_llm = bool(allow_llm and profile_obj.llm_allowed)
        if effective_allow_llm and self._should_upgrade_to_llm(report=report, failed_checks=failed_checks, failure_class=failure_class):
            upgraded = self._render_with_llm(report=report, base_message=message)
            if upgraded is not None:
                message = upgraded
        return self._apply_profile(message, profile_obj.name)


    def _apply_profile(self, message: FailureUserMessage, profile: str | None) -> FailureUserMessage:
        profile_obj = PresentationProfileRegistry.get(profile)
        technical = dict(message.technical or {}) if profile_obj.include_technical else {}
        technical["presentation_profile"] = profile_obj.name
        return FailureUserMessage(
            title=message.title,
            summary=message.summary,
            reasons=message.reasons[: profile_obj.max_reasons] if profile_obj.include_reasons else [],
            suggestions=message.suggestions[: profile_obj.max_suggestions] if profile_obj.include_suggestions else [],
            location=message.location[: profile_obj.max_location] if profile_obj.include_location else [],
            severity=message.severity,
            source=message.source,
            llm_used=message.llm_used,
            technical=technical,
        )

    def _render_deterministic(self, *, report: dict[str, Any], failure_class: str, failed_checks: list[dict[str, Any]]) -> FailureUserMessage:
        template = self.TEMPLATE_LIBRARY.get(failure_class) or self.TEMPLATE_LIBRARY["unknown_problem"]
        reasons = self._reason_lines(failed_checks)
        suggestions = list(template.get("suggestions") or [])
        suggestions.extend(self._suggestion_lines(failed_checks))
        location = self._location_lines(report=report, failed_checks=failed_checks)
        technical = {
            "failure_class": failure_class,
            "report_id": report.get("report_id"),
            "stage": report.get("stage") or (report.get("payload") or {}).get("stage"),
            "task_name": report.get("task_name"),
            "graph_id": report.get("graph_id"),
            "run_id": report.get("run_id"),
            "evidence_path": report.get("evidence_path"),
        }
        return FailureUserMessage(
            title=str(template.get("title") or "Runtime problem detected"),
            summary=str(template.get("summary") or "The runtime detected a problem."),
            reasons=self._dedupe(reasons)[:8],
            suggestions=self._dedupe([str(x) for x in suggestions if str(x).strip()])[:8],
            location=self._dedupe(location)[:8],
            severity=str(report.get("severity") or "error"),
            technical=technical,
        )

    def _render_with_llm(self, *, report: dict[str, Any], base_message: FailureUserMessage) -> FailureUserMessage | None:
        compact_report = {
            "failure_class": report.get("failure_class"),
            "status": report.get("status"),
            "stage": report.get("stage") or (report.get("payload") or {}).get("stage"),
            "task_name": report.get("task_name"),
            "failed_checks": self._compact_checks(report.get("failed_checks") if isinstance(report.get("failed_checks"), list) else []),
            "suggested_location": report.get("suggested_location"),
            "base_message": base_message.to_dict(),
        }
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a generic runtime presentation assistant. Convert a structured failure report "
                    "into a clear, concise user-facing explanation. Do not invent facts. Do not use domain-specific assumptions. "
                    "Return compact JSON with keys: title, summary, reasons, suggestions, location."
                ),
            },
            {"role": "user", "content": json.dumps(compact_report, ensure_ascii=False, default=str)},
        ]
        result = self.llm.complete_sync(
            brain="presentation_brain",
            task_type="failure_explanation",
            complexity="medium",
            messages=messages,
            context={"failure_class": report.get("failure_class"), "stage": compact_report.get("stage")},
            response_format={"type": "json_object"},
            temperature=0,
        )
        if result.status != "completed" or not result.content:
            base_message.technical["llm_explanation_status"] = result.status
            if result.error:
                base_message.technical["llm_explanation_error"] = result.error[:300]
            return None
        try:
            data = json.loads(result.content)
        except Exception:
            base_message.technical["llm_explanation_status"] = "invalid_json"
            return None
        if not isinstance(data, dict):
            return None
        return FailureUserMessage(
            title=str(data.get("title") or base_message.title),
            summary=str(data.get("summary") or base_message.summary),
            reasons=[str(x) for x in data.get("reasons", base_message.reasons) if str(x).strip()] if isinstance(data.get("reasons", []), list) else base_message.reasons,
            suggestions=[str(x) for x in data.get("suggestions", base_message.suggestions) if str(x).strip()] if isinstance(data.get("suggestions", []), list) else base_message.suggestions,
            location=[str(x) for x in data.get("location", base_message.location) if str(x).strip()] if isinstance(data.get("location", []), list) else base_message.location,
            severity=base_message.severity,
            source="presentation_brain.llm_upgraded_renderer",
            llm_used=True,
            technical={**base_message.technical, "llm_route": result.route, "llm_explanation_status": result.status},
        )

    def _should_upgrade_to_llm(self, *, report: dict[str, Any], failed_checks: list[dict[str, Any]], failure_class: str) -> bool:
        if failure_class in {"unknown_problem", "execution_verification_problem"}:
            return True
        classes = {str(check.get("failure_class") or "").strip() for check in failed_checks if str(check.get("failure_class") or "").strip()}
        levels = {str(check.get("level") or "").strip() for check in failed_checks if str(check.get("level") or "").strip()}
        if len(classes) >= 3 or len(levels) >= 3:
            return True
        if bool(report.get("force_llm_failure_explanation")):
            return True
        return False

    def _infer_primary_failure_class(self, failed_checks: list[dict[str, Any]]) -> str:
        for check in failed_checks:
            value = str(check.get("failure_class") or "").strip()
            if value:
                return value
        return "unknown_problem"

    def _reason_lines(self, failed_checks: list[dict[str, Any]]) -> list[str]:
        out: list[str] = []
        for check in failed_checks:
            if not isinstance(check, dict):
                continue
            label = str(check.get("message") or check.get("name") or check.get("check") or "A verification check failed.")
            detail_parts: list[str] = []
            for key in ("line", "reference", "root", "key", "status", "missing_reference", "participant_id", "generated_participant_id"):
                value = check.get(key)
                if value not in (None, "", [], {}):
                    detail_parts.append(f"{key}: {value}")
            suggestions = check.get("suggestions") if isinstance(check.get("suggestions"), list) else []
            if suggestions:
                detail_parts.append("suggestions: " + ", ".join(str(x) for x in suggestions[:4]))
            out.append(label + (" (" + "; ".join(detail_parts) + ")" if detail_parts else ""))
        return out

    def _suggestion_lines(self, failed_checks: list[dict[str, Any]]) -> list[str]:
        out: list[str] = []
        for check in failed_checks:
            for value in check.get("suggestions") if isinstance(check.get("suggestions"), list) else []:
                out.append(f"Consider existing candidate: {value}")
            cls = str(check.get("failure_class") or "")
            if cls == "template_reference_not_found" and check.get("declared_steps"):
                out.append("Use one of the declared step references: " + ", ".join(str(x) for x in check.get("declared_steps")[:8]))
        return out

    def _location_lines(self, *, report: dict[str, Any], failed_checks: list[dict[str, Any]]) -> list[str]:
        out: list[str] = []
        for value in report.get("suggested_location") if isinstance(report.get("suggested_location"), list) else []:
            out.append(str(value))
        for check in failed_checks:
            if check.get("line"):
                out.append(f"instruction line {check.get('line')}")
            if check.get("level"):
                out.append(f"verification level {check.get('level')}")
            for value in check.get("suggested_location") if isinstance(check.get("suggested_location"), list) else []:
                out.append(str(value))
        return out

    def _compact_checks(self, checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        compact: list[dict[str, Any]] = []
        allowed = {"level", "level_name", "name", "check", "failure_class", "message", "reference", "line", "suggestions", "status", "passed", "suggested_location"}
        for check in checks[:12]:
            if isinstance(check, dict):
                compact.append({k: v for k, v in check.items() if k in allowed})
        return compact

    def _dedupe_checks(self, checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Collapse repeated structural validation issues before rendering."""
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for check in checks:
            if not isinstance(check, dict):
                continue
            key_parts = [
                str(check.get("failure_class") or ""),
                str(check.get("check") or ""),
                str(check.get("reference") or ""),
                str(check.get("root") or ""),
                str(check.get("line") or ""),
            ]
            key = "|".join(key_parts).casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(check)
        return out

    def _dedupe(self, values: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = str(value or "").strip()
            if not text:
                continue
            key = text.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(text)
        return out


__all__ = ["FailureMessageRenderer", "FailureUserMessage"]
