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
                user_title="输入参数需要修复",
                user_message="执行所需的输入值缺失、格式不正确，或没有通过运行时 schema 校验。",
                repairable=True,
                suggested_action="检查并修复输入参数；如果原文中存在完整结构化值，可以用结构化抽取结果自动修复。",
                technical_reason=message,
                confidence=0.86,
                evidence=evidence,
            )
        if self._configuration_signal(code, text):
            return ExecutionFailureDiagnosis(
                category="configuration_problem",
                user_title="运行配置需要修复",
                user_message="工具配置文件缺少必要连接参数，或配置值没有通过 connection schema 校验。",
                repairable=True,
                suggested_action="打开对应 profile，补齐或修正连接配置后重新执行。",
                technical_reason=message,
                confidence=0.86,
                evidence=evidence,
            )
        if self._secret_signal(code, text):
            return ExecutionFailureDiagnosis(
                category="secret_problem",
                user_title="认证信息需要修复",
                user_message="外部服务拒绝了当前凭证，或 secret 值没有通过 secret schema 校验。",
                repairable=True,
                suggested_action="重新保存正确的账号凭证或访问令牌后重新执行。系统不会在日志中显示 secret 明文。",
                technical_reason=message,
                confidence=0.82,
                evidence=evidence,
            )
        if self._external_service_signal(code, text):
            return ExecutionFailureDiagnosis(
                category="external_service_problem",
                user_title="外部服务暂时无法完成请求",
                user_message="工具已经执行到外部服务，但外部服务返回失败、拒绝、超时或连接中断。",
                repairable=False,
                suggested_action="确认外部服务状态、网络、配额、权限或稍后重试。",
                technical_reason=message,
                confidence=0.72,
                evidence=evidence,
            )
        if self._implementation_signal(code, text, tool_spec):
            return ExecutionFailureDiagnosis(
                category="tool_implementation_problem",
                user_title="运行时工具实现需要修复",
                user_message="工具代码、输出契约或运行时实现可能存在问题，需要由 auxiliary_brain 读取 trace 后生成补丁并重新验证。",
                repairable=True,
                suggested_action="生成工具修复请求，由 auxiliary_brain 创建 patch、运行 sandbox 验证，并在验证通过后注册新版本。",
                technical_reason=message,
                confidence=0.77,
                evidence=evidence,
            )
        return ExecutionFailureDiagnosis(
            category="unknown_problem",
            user_title="执行失败，需要人工确认修复方向",
            user_message="系统没有足够结构化信号判断失败类型。",
            repairable=False,
            suggested_action="查看 runtime/traces 与 runtime/logs 中的详细信息后再决定是否修复。",
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
