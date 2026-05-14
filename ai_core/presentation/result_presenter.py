from __future__ import annotations

from typing import Any


class ResultPresenter:
    """Turns generic runtime result dictionaries into user-facing text.

    This module is intentionally domain-neutral. It does not know specific
    business capabilities. It only formats structured data, evidence quality,
    and extracted text using generic conventions.
    """

    INTERNAL_KEYS = {
        "status",
        "source",
        "requires_human_confirmation",
        "provenance",
        "fallback_attempts",
        "answer_material_quality",
        "extracted_text",
        "raw",
        "debug",
        "trace",
    }

    PREFERRED_TEXT_KEYS = ("final_answer", "answer", "summary", "message", "text")

    def present_tool_result(self, tool_result: dict[str, Any]) -> str:
        if not isinstance(tool_result, dict):
            return "The step completed."

        for key in self.PREFERRED_TEXT_KEYS:
            value = tool_result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        data = tool_result.get("data")
        if isinstance(data, dict):
            for key in self.PREFERRED_TEXT_KEYS:
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            return self.present_data(data)
        if data is not None:
            return f"The step completed with result: {self._scalar(data)}"
        return "The step completed successfully."

    def present_data(self, data: dict[str, Any]) -> str:
        public_items = [(k, v) for k, v in data.items() if k not in self.INTERNAL_KEYS]
        if not public_items:
            return "The requested information was retrieved successfully."

        # If there is exactly one structured payload, present that directly.
        if len(public_items) == 1 and isinstance(public_items[0][1], dict):
            title = self._label(public_items[0][0])
            body = self._format_dict(public_items[0][1], level=0)
            return f"{title}:\n{body}" if body else f"{title}: retrieved successfully."

        lines = ["Result:"]
        for key, value in public_items:
            label = self._label(key)
            formatted = self._format_value(value, level=1)
            if "\n" in formatted:
                lines.append(f"- {label}:")
                lines.extend(f"  {line}" if line else "" for line in formatted.splitlines())
            else:
                lines.append(f"- {label}: {formatted}")
        return "\n".join(lines)

    def evidence_quality_passed(self, tool_result: dict[str, Any]) -> bool:
        if not isinstance(tool_result, dict):
            return False
        candidates: list[Any] = []
        data = tool_result.get("data")
        if isinstance(data, dict):
            candidates.append(data.get("answer_material_quality"))
        candidates.append(tool_result.get("answer_material_quality"))
        for item in candidates:
            if isinstance(item, dict) and item.get("passed") is True:
                return True
        return False

    def _format_value(self, value: Any, *, level: int = 0) -> str:
        if isinstance(value, dict):
            return self._format_dict(value, level=level)
        if isinstance(value, list):
            return self._format_list(value, level=level)
        return self._scalar(value)

    def _format_dict(self, value: dict[str, Any], *, level: int = 0) -> str:
        lines: list[str] = []
        for key, item in value.items():
            if key in self.INTERNAL_KEYS:
                continue
            label = self._label(key)
            if isinstance(item, dict):
                lines.append(f"- {label}:")
                nested = self._format_dict(item, level=level + 1)
                lines.extend(f"  {line}" if line else "" for line in nested.splitlines())
            elif isinstance(item, list):
                lines.append(f"- {label}:")
                nested = self._format_list(item, level=level + 1)
                lines.extend(f"  {line}" if line else "" for line in nested.splitlines())
            else:
                lines.append(f"- {label}: {self._scalar(item)}")
        return "\n".join(lines)

    def _format_list(self, value: list[Any], *, level: int = 0) -> str:
        if not value:
            return "None"
        lines: list[str] = []
        for item in value:
            if isinstance(item, dict):
                compact = self._compact_dict(item)
                if compact:
                    lines.append(f"- {compact}")
                else:
                    nested = self._format_dict(item, level=level + 1)
                    lines.append("-")
                    lines.extend(f"  {line}" if line else "" for line in nested.splitlines())
            elif isinstance(item, list):
                lines.append(f"- {self._format_list(item, level=level + 1)}")
            else:
                lines.append(f"- {self._scalar(item)}")
        return "\n".join(lines)

    def _compact_dict(self, value: dict[str, Any]) -> str:
        public = [(k, v) for k, v in value.items() if k not in self.INTERNAL_KEYS]
        if not public:
            return ""
        parts: list[str] = []
        for key, item in public:
            if isinstance(item, (dict, list)):
                return ""
            parts.append(f"{self._label(key)}: {self._scalar(item)}")
        return "; ".join(parts)

    def _label(self, key: Any) -> str:
        text = str(key).replace("_", " ").replace("-", " ").strip()
        if not text:
            return str(key)
        return " ".join(part[:1].upper() + part[1:] for part in text.split())

    def _scalar(self, value: Any) -> str:
        if value is None:
            return "None"
        if isinstance(value, bool):
            return "Yes" if value else "No"
        return str(value)
