from __future__ import annotations

from typing import Any


class ResultClassifier:
    """Classify generic runtime execution results for retry/fallback routing.

    This class is domain-neutral. It only examines generic status, error codes,
    messages, and transport-like failure hints. It does not know what the
    capability means.
    """

    RETRYABLE_HINTS = {
        "timeout",
        "timed out",
        "403",
        "401",
        "forbidden",
        "unauthorized",
        "invalid_json",
        "html_not_json",
        "html_page_detected",
        "unsupported_content_type",
        "connection",
        "network",
        "rate limit",
        "too many requests",
        "cloudflare",
        "captcha",
    }

    AUTH_HINTS = {"401", "403", "forbidden", "unauthorized", "api key", "authentication"}
    TIMEOUT_HINTS = {"timeout", "timed out"}
    JSON_HINTS = {"invalid_json", "html_not_json", "html_page_detected", "unsupported_content_type"}

    def classify(self, result: Any) -> dict[str, Any]:
        if not isinstance(result, dict):
            return {"success": False, "retryable": False, "category": "invalid_result", "reason": "Result is not an object."}

        status = str(result.get("status", "")).lower().strip()
        error = result.get("error")
        message = self._message(result)
        lower = message.lower()

        if status in {"success", "ok", "executed"} and not error:
            return {"success": True, "retryable": False, "category": "success", "reason": "Runtime result succeeded."}

        if any(hint in lower for hint in self.TIMEOUT_HINTS):
            return {"success": False, "retryable": True, "category": "timeout", "reason": message}
        if any(hint in lower for hint in self.AUTH_HINTS):
            return {"success": False, "retryable": True, "category": "auth_or_blocked", "reason": message}
        if any(hint in lower for hint in self.JSON_HINTS):
            return {"success": False, "retryable": True, "category": "content_type_or_parse", "reason": message}
        if any(hint in lower for hint in self.RETRYABLE_HINTS):
            return {"success": False, "retryable": True, "category": "retryable_external_failure", "reason": message}

        return {"success": False, "retryable": False, "category": "non_retryable_failure", "reason": message or "Runtime result failed."}

    def _message(self, result: dict[str, Any]) -> str:
        error = result.get("error")
        if isinstance(error, dict):
            parts = [str(error.get(k) or "") for k in ["code", "message", "type", "reason"]]
            text = " ".join(part for part in parts if part)
            if text:
                return text
        if error:
            return str(error)
        for key in ["message", "reason", "details"]:
            if result.get(key):
                return str(result.get(key))
        return str(result)
