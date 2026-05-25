from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import re


_EMPTY_VALUES = (None, "", [], {})


@dataclass
class PreflightResolutionContext:
    """Typed result for pre-execution requirement resolution.

    The context keeps user supplied execution inputs, runtime resource bindings,
    and scheduler/executor policies separate.  The UI can still ask for all
    missing values once, but execution code does not mix resources or policies
    into callable input dictionaries.
    """

    resolved_inputs: dict[str, Any] = field(default_factory=dict)
    bound_resources: dict[str, Any] = field(default_factory=dict)
    execution_policies: dict[str, Any] = field(default_factory=dict)
    missing_input_fields: list[dict[str, Any]] = field(default_factory=list)
    resource_binding_reports: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def requires_input(self) -> bool:
        return bool(self.missing_input_fields)

    def to_analysis(self) -> dict[str, Any]:
        return {
            "resolved_inputs": dict(self.resolved_inputs),
            "bound_resources": dict(self.bound_resources),
            "execution_policies": dict(self.execution_policies),
            "missing_input_fields": list(self.missing_input_fields),
            "resource_binding_reports": list(self.resource_binding_reports),
            "notes": list(self.notes),
        }


class ParameterResolutionPipeline:
    """Resolve pre-execution requirements without flattening all context.

    This class is intentionally generic: it does not know domain names or task
    semantics.  Callers provide discovered fields, resource reports, existing
    run inputs, and policy flags; the pipeline deduplicates only by stable field
    identity and returns a typed context for the next layer.
    """

    def build_context(
        self,
        *,
        runtime_inputs: dict[str, Any] | None = None,
        resource_reports: list[dict[str, Any]] | None = None,
        agent_fields: list[dict[str, Any]] | None = None,
        policy_values: dict[str, Any] | None = None,
        bound_resources: dict[str, Any] | None = None,
    ) -> PreflightResolutionContext:
        context = PreflightResolutionContext()
        context.resolved_inputs.update(self._clean_mapping(runtime_inputs or {}))
        context.bound_resources.update(self._clean_mapping(bound_resources or {}))
        context.execution_policies.update(self._clean_mapping(policy_values or {}))

        for report in resource_reports or []:
            if not isinstance(report, dict):
                continue
            context.resource_binding_reports.append(report)
            resources = report.get("bound_resources") if isinstance(report.get("bound_resources"), dict) else {}
            context.bound_resources.update(self._clean_mapping(resources))
            policies = report.get("execution_policies") if isinstance(report.get("execution_policies"), dict) else {}
            context.execution_policies.update(self._clean_mapping(policies))
            for field in report.get("missing_inputs") or []:
                self._append_missing_field(context, field, source_hint="resource_binding")

        for field in agent_fields or []:
            self._append_missing_field(context, field, source_hint="execution_input")

        context.missing_input_fields = self._dedupe_fields(context.missing_input_fields, context.resolved_inputs)
        return context

    def _append_missing_field(self, context: PreflightResolutionContext, field: Any, *, source_hint: str) -> None:
        normalized = self._normalize_field(field, source_hint=source_hint)
        if normalized:
            context.missing_input_fields.append(normalized)

    def _normalize_field(self, field: Any, *, source_hint: str) -> dict[str, Any] | None:
        if isinstance(field, dict):
            name = str(field.get("field") or field.get("name") or field.get("parameter_name") or "").strip()
            if not name:
                return None
            out = dict(field)
            out.setdefault("field", name)
            out.setdefault("name", name)
            out.setdefault("label", field.get("label") or name)
            out.setdefault("input_type", field.get("input_type") or field.get("type") or "text")
            out.setdefault("required", field.get("required", True))
            out.setdefault("resolution_layer", source_hint)
            return out
        if isinstance(field, str) and field.strip():
            name = field.strip()
            return {"field": name, "name": name, "label": name, "input_type": "text", "required": True, "resolution_layer": source_hint}
        return None

    def _dedupe_fields(self, fields: list[dict[str, Any]], resolved_inputs: dict[str, Any]) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for field in fields:
            key = self.field_key(field)
            raw_name = str(field.get("field") or field.get("name") or "").strip()
            if not key or key in seen:
                continue
            if raw_name and resolved_inputs.get(raw_name) not in _EMPTY_VALUES:
                continue
            seen.add(key)
            deduped.append(field)
        return deduped

    def field_key(self, field: dict[str, Any]) -> str:
        raw = str(field.get("field") or field.get("name") or field.get("parameter_name") or "").strip()
        participant = str(field.get("participant_id") or "").strip()
        layer = str(field.get("resolution_layer") or field.get("source") or field.get("kind") or "").strip()
        normalized = re.sub(r"[^a-z0-9]+", "_", raw.casefold()).strip("_")
        return "|".join(part for part in (layer, participant, normalized) if part)

    def _clean_mapping(self, values: dict[str, Any]) -> dict[str, Any]:
        return {str(k): v for k, v in values.items() if v not in _EMPTY_VALUES}
