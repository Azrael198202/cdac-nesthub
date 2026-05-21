from __future__ import annotations

import json
import re


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


def parse_json_content(content: str) -> dict:
    content = (content or "").strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?", "", content).strip()
        content = re.sub(r"```$", "", content).strip()
    return json.loads(content)
