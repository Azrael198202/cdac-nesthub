from __future__ import annotations

import json
from typing import Any

_BLOCKED = {"", "completed", "success", "ok", "conversation_message", "runtime_response"}


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    except Exception:
        return str(value)


def _status_icon(ok: bool | None, status: str = "") -> str:
    if ok is True or status in {"success", "completed", "registered"}:
        return "✅"
    if ok is False or status in {"failed", "error"}:
        return "❌"
    return "ℹ️"


def _extract_tool_body(payload: dict[str, Any]) -> Any:
    if not isinstance(payload, dict):
        return payload
    result = payload.get("result")
    if isinstance(result, dict):
        nested = result.get("result")
        if nested not in (None, ""):
            return nested
        data = result.get("data")
        if data not in (None, {}, ""):
            return data
    for key in ("tool_result", "data", "output", "normalized_result"):
        if payload.get(key) not in (None, {}, ""):
            return payload.get(key)
    return payload


def _extract_schedule_like_summary(body: Any) -> list[str]:
    """Generic structural summary: no capability names are hard-coded."""
    if not isinstance(body, dict):
        return []
    lines: list[str] = []
    for key in ("operation", "success", "affected_count", "schedule_id", "id"):
        if key in body and body.get(key) not in (None, ""):
            lines.append(f"- {key}: {body.get(key)}")
    result = body.get("result")
    if isinstance(result, dict):
        for key in ("schedule_id", "title", "start_time", "end_time", "timezone", "status"):
            if key in result and result.get(key) not in (None, ""):
                lines.append(f"- {key}: {result.get(key)}")
    elif isinstance(result, list):
        lines.append(f"- result_count: {len(result)}")
        for idx, item in enumerate(result[:5], 1):
            if isinstance(item, dict):
                title = item.get("title") or item.get("name") or item.get("id") or item.get("schedule_id") or f"item {idx}"
                extra = item.get("start_time") or item.get("status") or ""
                lines.append(f"  {idx}. {title}{(' — ' + str(extra)) if extra else ''}")
    return lines


def render_runtime_response(payload: Any, *, profile: str = "user") -> str:
    """Render runtime output through presentation profiles.

    Profiles are generic display levels:
    - user: concise user-facing answer
    - advanced: useful runtime summary
    - developer: formatted primary payload
    - diagnostic: full diagnostic JSON
    """
    profile = (profile or "user").strip().lower()
    if not isinstance(payload, dict):
        return str(payload)
    ok = payload.get("ok")
    status = str(payload.get("status") or payload.get("result", {}).get("status") or "").strip().lower()
    tool_id = str(payload.get("tool_id") or payload.get("result", {}).get("tool_id") or "").strip()
    body = _extract_tool_body(payload)

    if profile == "diagnostic":
        return "Diagnostic runtime payload:\n\n```json\n" + _safe_json(payload) + "\n```"

    if profile == "developer":
        return "Developer runtime result:\n\n```json\n" + _safe_json(body) + "\n```"

    if ok is False or status in {"failed", "error"}:
        msg = payload.get("human_readable_error") or payload.get("message")
        if not msg and isinstance(payload.get("error"), dict):
            msg = payload["error"].get("message")
        if not msg and isinstance(payload.get("result"), dict):
            err = payload["result"].get("error")
            if isinstance(err, dict):
                msg = err.get("message")
        msg = msg or "Runtime execution failed."
        if profile == "advanced":
            return f"{_status_icon(False, status)} Runtime execution failed.\n\n{msg}\n\n```json\n{_safe_json(body)}\n```"
        return f"{_status_icon(False, status)} {msg}"

    lines = _extract_schedule_like_summary(body)
    if profile == "advanced":
        head = f"{_status_icon(True, status)} Runtime execution completed."
        if tool_id:
            head += f"\n\nTool: `{tool_id}`"
        if lines:
            head += "\n\n" + "\n".join(lines)
        head += "\n\n<details><summary>Structured result</summary>\n\n```json\n" + _safe_json(body) + "\n```\n</details>"
        return head

    # user profile
    if lines:
        return f"{_status_icon(True, status)} 操作已完成。\n\n" + "\n".join(lines)
    text = ""
    for key in ("final_answer", "message", "answer", "summary"):
        v = str(payload.get(key) or "").strip()
        if v and v.lower() not in _BLOCKED:
            text = v
            break
    return text or f"{_status_icon(True, status)} 操作已完成。"
