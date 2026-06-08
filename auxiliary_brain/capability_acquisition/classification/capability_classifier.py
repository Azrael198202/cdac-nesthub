from __future__ import annotations

import json
import re
from typing import Any

from .capability_class import CapabilityClass


class CapabilityClassifier:
    """Classify capability acquisition requirements without domain knowledge.

    The classifier only evaluates structural/policy constraints declared by the
    request or blueprint: local runtime execution, standard-library-only code,
    external dependency requirements, and explicit network/API prohibitions.
    It intentionally does not match concrete capability names.
    """

    def classify(
        self,
        *,
        user_input: str,
        template: dict[str, Any],
        planner_record: dict[str, Any],
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        text = self._contract_text(user_input=user_input, template=template, planner_record=planner_record)
        has_external_evidence = bool(isinstance(evidence, dict) and evidence.get("urls"))
        dependency = self._declares_external_dependency(template)
        local_policy = self.is_policy_backed_basic(user_input=user_input, template=template, evidence=evidence)
        positive = [marker for marker in self._positive_markers() if marker in text]
        negative = [marker for marker in self._external_requirement_markers() if self._has_unnegated_marker(text, marker)]

        if dependency:
            capability_class = CapabilityClass.DEPENDENCY_BACKED
            runtime_native = False
        elif negative:
            capability_class = CapabilityClass.EXTERNAL_EVIDENCE_REQUIRED
            runtime_native = False
        elif local_policy or positive:
            capability_class = CapabilityClass.RUNTIME_NATIVE
            runtime_native = True
        else:
            capability_class = CapabilityClass.EXTERNAL_EVIDENCE_REQUIRED
            runtime_native = False

        return {
            "runtime_native": runtime_native,
            "class": capability_class.value,
            "positive_markers": positive,
            "negative_markers": negative,
            "declares_external_dependency": dependency,
            "has_external_evidence": has_external_evidence,
            "policy_backed_basic": local_policy,
            "policy": "policy_backed_without_external_evidence" if runtime_native and not has_external_evidence else "normal",
        }

    def is_policy_backed_basic(self, *, user_input: str, template: dict[str, Any], evidence: dict[str, Any]) -> bool:
        text = self._contract_text(user_input=user_input, template=template, planner_record={})
        if self._declares_external_dependency(template):
            return False
        standard_library_only = "standard library" in text or "standard-library" in text
        low_complexity = "basic" in text or "low complexity" in text
        local_safety = any(marker in text for marker in self._local_safety_markers())
        dynamic_value = any(marker in text for marker in self._dynamic_value_markers())
        external_requirement = any(self._has_unnegated_marker(text, marker) for marker in self._external_requirement_markers())
        return standard_library_only and low_complexity and local_safety and dynamic_value and not external_requirement

    def _contract_text(self, *, user_input: str, template: dict[str, Any], planner_record: dict[str, Any]) -> str:
        payload = {
            "user_input": user_input,
            "template": {
                "description": template.get("description") if isinstance(template, dict) else "",
                "acquisition_policy": template.get("acquisition_policy") if isinstance(template, dict) else {},
                "runtime_execution_policy": template.get("runtime_execution_policy") if isinstance(template, dict) else {},
                "dependencies": template.get("dependencies") if isinstance(template, dict) else [],
            },
            "planner": {"needs_external_evidence": planner_record.get("needs_external_evidence") if isinstance(planner_record, dict) else None},
        }
        return json.dumps(payload, ensure_ascii=False, default=str).casefold()

    def _declares_external_dependency(self, template: dict[str, Any]) -> bool:
        dependencies = template.get("dependencies") if isinstance(template.get("dependencies"), list) else []
        return any(
            isinstance(item, dict)
            and str(item.get("package") or item.get("name") or item.get("module") or "").strip()
            for item in dependencies
        )

    def _positive_markers(self) -> list[str]:
        return [
            "standard library",
            "standard-library",
            "no external package",
            "do not require external",
            "without external package",
            "no package installation",
            "do not require package installation",
            "do not call external network",
            "no external network",
            "no network api",
            "no network apis",
            "offline",
            "deterministic local",
            "do not return a hardcoded",
            "not hardcoded",
            "local runtime",
            "local storage",
            "runtime storage",
            "basic",
        ]

    def _local_safety_markers(self) -> list[str]:
        return [
            "no external package",
            "do not require external package",
            "without external package",
            "no package installation",
            "do not require package installation",
            "do not call external api",
            "do not call external apis",
            "do not call external network",
            "no external network",
            "no network api",
            "no network apis",
            "offline",
        ]

    def _dynamic_value_markers(self) -> list[str]:
        return [
            "do not return a hardcoded",
            "not hardcoded",
            "runtime value",
            "derived at execution",
            "execution time",
            "when executed",
            "at execution",
        ]

    def _external_requirement_markers(self) -> list[str]:
        return [
            "external api",
            "external apis",
            "oauth",
            "browser automation",
            "third-party sdk",
            "pip install",
            "requires external package",
            "require external package",
            "external package",
            "external network",
            "network api",
            "network apis",
        ]

    def _has_unnegated_marker(self, text: str, marker: str) -> bool:
        """Return True only when marker is not explicitly prohibited.

        Example: "do not call external APIs" contains "external api", but it is
        a local-safety constraint, not an external requirement.
        """
        marker = marker.casefold()
        for match in re.finditer(re.escape(marker), text):
            start = max(0, match.start() - 48)
            prefix = text[start:match.start()]
            if re.search(r"(do\s+not|don't|must\s+not|without|no|not|禁止|不要|不使用|不调用)\s+[\w\s-]{0,32}$", prefix):
                continue
            return True
        return False
