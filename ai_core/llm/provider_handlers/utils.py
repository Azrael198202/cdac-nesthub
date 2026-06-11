from __future__ import annotations

import json
import re
from typing import Any
from ai_core.llm.json_repair import repair_json_object_text


class LLMJSONParseError(ValueError):
    """Raised when a model response cannot be parsed as JSON.

    The raw content is kept so the caller can record it to runtime traces and
    optionally run a retry/repair strategy. This prevents the generic provider
    router from misreporting parse failures as provider availability failures.
    """

    def __init__(self, message: str, *, raw_content: str, candidate: str | None = None) -> None:
        super().__init__(message)
        self.raw_content = raw_content
        self.candidate = candidate or raw_content


def build_system_prompt(prompt: dict, schema: dict, *, max_schema_chars: int = 12000) -> str:
    schema_text = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    if len(schema_text) > max_schema_chars:
        schema_text = schema_text[:max_schema_chars] + "...[schema truncated by provider budget]"
    return (
        str(prompt.get("system", ""))
        + "\n\nReturn exactly one valid JSON object. No markdown. No explanation."
        + "\nJSON Schema:\n"
        + schema_text
    )


def parse_json_content(content: str) -> dict[str, Any]:
    raw = content or ""
    cleaned = _strip_wrappers(raw)
    candidates = _candidate_json_strings(cleaned)
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
            raise LLMJSONParseError("Parsed JSON is not an object", raw_content=raw, candidate=candidate)
        except Exception as exc:
            last_error = exc
            repaired = _light_repair(candidate)
            if repaired != candidate:
                try:
                    parsed = json.loads(repaired)
                    if isinstance(parsed, dict):
                        return parsed
                except Exception as repair_exc:
                    last_error = repair_exc
    structural = repair_json_object_text(raw)
    if structural.parsed is not None:
        return structural.parsed
    msg = structural.error or str(last_error or "invalid JSON")
    raise LLMJSONParseError(msg, raw_content=raw, candidate=structural.text or (candidates[0] if candidates else cleaned))


def _strip_wrappers(text: str) -> str:
    s = (text or "").strip()
    # Remove common thinking blocks before JSON extraction.
    s = re.sub(r"<think>.*?</think>", "", s, flags=re.DOTALL | re.IGNORECASE).strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?", "", s, flags=re.IGNORECASE).strip()
        s = re.sub(r"```$", "", s).strip()
    return s


def _candidate_json_strings(text: str) -> list[str]:
    candidates: list[str] = []
    s = text.strip()
    if s:
        candidates.append(s)
    obj = _extract_first_balanced_object(s)
    if obj and obj not in candidates:
        candidates.append(obj)
    arr = _extract_first_balanced_array(s)
    if arr and arr not in candidates:
        candidates.append(arr)
    # Remove duplicate candidates while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _extract_first_balanced_object(text: str) -> str | None:
    return _extract_balanced(text, "{", "}")


def _extract_first_balanced_array(text: str) -> str | None:
    return _extract_balanced(text, "[", "]")


def _extract_balanced(text: str, open_ch: str, close_ch: str) -> str | None:
    start = text.find(open_ch)
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start:idx + 1]
    return None


def _light_repair(text: str) -> str:
    s = text.strip()
    # Full-width/smart quotes sometimes appear in local model output.
    s = s.replace("“", '"').replace("”", '"').replace("’", "'")
    # Remove trailing commas before object/array close.
    s = re.sub(r",\s*([}\]])", r"\1", s)
    # Convert Python-style booleans/nulls if the model copied a Python repr.
    s = re.sub(r"\bTrue\b", "true", s)
    s = re.sub(r"\bFalse\b", "false", s)
    s = re.sub(r"\bNone\b", "null", s)
    return s
