from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ExecutionFailureDiagnosis:
    category: str
    user_title: str
    user_message: str
    repairable: bool
    requires_user_confirmation: bool = True
    suggested_action: str = ""
    technical_reason: str = ""
    confidence: float = 0.0
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ExecutionFailureRepairClassifier:
    """Classify runtime execution failures using generic structural signals.

    The classifier does not know any concrete capability. It looks at declared
    schema sections, error envelopes, status codes, and generic security /
    configuration / format / implementation signals.
    """

    def classify(self, *, result: dict[str, Any], tool_spec: dict[str, Any] | None = None) -> ExecutionFailureDiagnosis:
        tool_spec = tool_spec if isinstance(tool_spec, dict) else {}
        result = result if isinstance(result, dict) else {}
        error = self._error_object(result)
        code = str(error.get("code") or result.get("status") or "").strip()
        message = str(error.get("message") or result.get("message") or error or "")
        text = " ".join([code, message, str(error.get("errors") or "")]).casefold()
        evidence = {"error_code": code, "message": message[-1000:], "status": result.get("status")}

        if self._schema_or_parameter_signal(code, text):
            return ExecutionFailureDiagnosis(
                category="parameter_problem",
                user_title="Input values need repair",
                user_message="The runtime input values are missing, malformed, or did not pass the declared runtime schema validation.",
                repairable=True,
                suggested_action="Review and repair the input values. If the original request contains a complete structural value, the runtime can use the extracted structural value to repair the input.",
                technical_reason=message,
                confidence=0.86,
                evidence=evidence,
            )
        if self._configuration_signal(code, text):
            return ExecutionFailureDiagnosis(
                category="configuration_problem",
                user_title="Runtime configuration needs repair",
                user_message="The selected runtime profile is missing required connection settings, or the values did not pass the declared connection schema validation.",
                repairable=True,
                suggested_action="Open the selected profile, complete or correct the connection settings, and run the task again.",
                technical_reason=message,
                confidence=0.86,
                evidence=evidence,
            )
        if self._secret_signal(code, text):
            return ExecutionFailureDiagnosis(
                category="secret_problem",
                user_title="Credential values need repair",
                user_message="The runtime rejected the current credential values, or the secret values did not pass the declared secret schema validation.",
                repairable=True,
                suggested_action="Save the correct credential or access-token values in the selected profile and run the task again. Secret values are not shown in logs.",
                technical_reason=message,
                confidence=0.82,
                evidence=evidence,
            )
        if self._external_service_signal(code, text):
            return ExecutionFailureDiagnosis(
                category="external_service_problem",
                user_title="The external runtime could not complete the request",
                user_message="The tool reached the external runtime, but the external runtime returned a failure, refusal, timeout, or connection interruption.",
                repairable=False,
                suggested_action="Check the external runtime status, network, quota, permissions, or retry later.",
                technical_reason=message,
                confidence=0.72,
                evidence=evidence,
            )
        if self._implementation_signal(code, text, tool_spec):
            return ExecutionFailureDiagnosis(
                category="tool_implementation_problem",
                user_title="Runtime tool implementation needs repair",
                user_message="The tool code, output contract, or runtime implementation may be incorrect. The auxiliary layer should read the trace, generate a patch, and revalidate it.",
                repairable=True,
                suggested_action="Create a tool repair request. The auxiliary layer will generate a patch, run sandbox validation, and register a new version only after verification passes.",
                technical_reason=message,
                confidence=0.77,
                evidence=evidence,
            )
        return ExecutionFailureDiagnosis(
            category="unknown_problem",
            user_title="Execution failed and needs human review",
            user_message="The runtime did not provide enough structured signals to classify the failure safely.",
            repairable=False,
            suggested_action="Review the detailed runtime traces and logs before deciding how to repair it.",
            technical_reason=message,
            confidence=0.3,
            evidence=evidence,
        )

    def _error_object(self, result: dict[str, Any]) -> dict[str, Any]:
        if isinstance(result.get("error"), dict):
            return result["error"]
        nested = result.get("result") if isinstance(result.get("result"), dict) else {}
        if isinstance(nested.get("error"), dict):
            return nested["error"]
        if result.get("error"):
            return {"message": str(result.get("error"))}
        return {}

    def _schema_or_parameter_signal(self, code: str, text: str) -> bool:
        if "input_schema" in code or "schema_validation" in code or "parameter" in code:
            return True
        generic_terms = ["missing", "required", "format", "invalid", "not valid", "additional property", "value error"]
        return any(term in text for term in generic_terms) and not self._secret_signal(code, text)

    def _configuration_signal(self, code: str, text: str) -> bool:
        if "connection_schema" in code or "configuration" in code or "profile" in code:
            return True
        # Network/runtime availability words should be treated as external
        # execution signals, even when they mention a generic endpoint.
        if self._external_service_signal(code, text):
            return False
        words = set(text.replace("_", " ").replace("-", " ").split())
        return any(term in words for term in ["connection", "configured", "endpoint", "port", "host", "profile"])

    def _secret_signal(self, code: str, text: str) -> bool:
        if "secret_schema" in code or "secret" in code or "credential" in code:
            return True
        return any(term in text for term in ["authentication", "auth", "credential", "password", "username", "token", "login", "not accepted", "unauthorized", "forbidden"])

    def _external_service_signal(self, code: str, text: str) -> bool:
        return any(term in text for term in ["timeout", "temporarily", "rate limit", "quota", "connection closed", "connection reset", "service unavailable", "too many", "refused"])

    def _implementation_signal(self, code: str, text: str, tool_spec: dict[str, Any]) -> bool:
        impl = tool_spec.get("implementation") if isinstance(tool_spec.get("implementation"), dict) else {}
        if code in {"tool_execution_failed", "tool_output_schema_validation_failed", "module_not_found", "missing_module_path"}:
            return True
        if not impl:
            return True
        return any(term in text for term in ["traceback", "exception", "typeerror", "keyerror", "attributeerror", "not implemented", "unsupported"])
