from __future__ import annotations

import json
import re
from typing import Any


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


def _extract_first_json_object(text: str) -> str | None:
    """Extract the first balanced JSON object from arbitrary model text.

    This is generic and domain-free. It prevents a single provider that returns
    explanatory text, HTML, or an HTTP error body from crashing the whole runtime
    with an opaque JSONDecodeError.
    """
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for index, ch in enumerate(text[start:], start=start):
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
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None


def parse_json_content(content: str) -> dict[str, Any]:
    raw = str(content or "").strip()
    if not raw:
        raise ValueError("Provider returned empty content; expected one JSON object.")
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?", "", raw).strip()
        raw = re.sub(r"```$", "", raw).strip()
    candidates = [raw]
    extracted = _extract_first_json_object(raw)
    if extracted and extracted != raw:
        candidates.append(extracted)
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            value = json.loads(candidate)
            if isinstance(value, dict):
                return value
            raise ValueError(f"JSON root must be object, got {type(value).__name__}.")
        except Exception as exc:  # keep trying extracted fallback
            last_error = exc
    preview = raw[:240].replace("\n", " ")
    raise ValueError(f"Provider returned non-JSON content. preview={preview!r}; parse_error={last_error}")


def response_json_or_error(response: Any, *, provider_name: str, endpoint: str) -> dict[str, Any]:
    try:
        data = response.json()
    except Exception as exc:
        text = getattr(response, "text", "") or ""
        preview = str(text)[:500].replace("\n", " ")
        status = getattr(response, "status_code", "unknown")
        raise ValueError(
            f"Provider HTTP response was not JSON. provider={provider_name}, endpoint={endpoint}, "
            f"status={status}, preview={preview!r}"
        ) from exc
    if not isinstance(data, dict):
        raise ValueError(f"Provider HTTP response JSON root must be object. provider={provider_name}, endpoint={endpoint}")
    return data
