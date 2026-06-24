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


def _non_empty(value: Any) -> bool:
    return value not in (None, "", {}, [])


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if _non_empty(value):
            return value
    return None


def _extract_tool_body(payload: dict[str, Any]) -> Any:
    """Extract the meaningful tool payload without assuming a capability type."""
    if not isinstance(payload, dict):
        return payload

    for key in ("tool_result", "normalized_result", "output", "data"):
        value = payload.get(key)
        if _non_empty(value):
            return value

    result = payload.get("result")
    if isinstance(result, dict):
        for key in ("result", "data", "output", "tool_result", "normalized_result"):
            value = result.get(key)
            if _non_empty(value):
                return value
        return result
    if _non_empty(result):
        return result
    return payload


def _short_value(value: Any, limit: int = 140) -> str:
    if isinstance(value, (dict, list)):
        text = _safe_json(value).replace("\n", " ")
    else:
        text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _first_key(item: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in item and _non_empty(item.get(key)):
            return item.get(key)
    return None


_TITLE_KEYS = ("title", "name", "label", "subject", "summary", "caption", "heading")
_DESCRIPTION_KEYS = ("description", "summary", "content", "body", "message", "detail", "notes", "note")
_START_KEYS = ("start_time", "start", "from", "begin", "datetime", "date", "time", "created_at")
_END_KEYS = ("end_time", "end", "to", "finish", "due_time", "updated_at")
_ID_KEYS = ("id", "record_id", "schedule_id", "item_id", "event_id", "task_id", "tool_id")
_LOCATION_KEYS = ("location", "place", "venue", "address")
_STATUS_KEYS = ("status", "state", "phase")
_OWNER_KEYS = ("user", "owner", "schedule_user", "assignee", "created_by")
_URL_KEYS = ("url", "link", "source_url", "href")
_TAG_KEYS = ("tags", "categories", "labels")
_TIMEZONE_KEYS = ("timezone", "time_zone", "tz")


def _item_title(item: dict[str, Any], idx: int) -> str:
    value = _first_key(item, _TITLE_KEYS + _ID_KEYS)
    if value not in (None, ""):
        return str(value)
    return f"Item {idx}"


def _format_time_range(item: dict[str, Any]) -> str:
    start = _first_key(item, _START_KEYS)
    end = _first_key(item, _END_KEYS)
    if start and end and start != end:
        return f"{_short_value(start)} - {_short_value(end)}"
    if start:
        return _short_value(start)
    if end:
        return _short_value(end)
    return ""


def _compact_list(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(_short_value(v, 50) for v in value[:8])
    return _short_value(value)


def _item_detail_lines(item: dict[str, Any]) -> list[str]:
    """Return generic, high-value fields for a result record.

    The key groups are common across many capability domains: title/name,
    description/body, time/date, location, status, owner, tags, URL, and IDs.
    No capability-specific words or language-specific sentences are hard-coded.
    """
    lines: list[str] = []

    description = _first_key(item, _DESCRIPTION_KEYS)
    title = _first_key(item, _TITLE_KEYS)
    if description and description != title:
        lines.append(f"- Description: {_short_value(description, 180)}")

    time_range = _format_time_range(item)
    if time_range:
        lines.append(f"- Time: {time_range}")

    for label, keys in (
        ("Location", _LOCATION_KEYS),
        ("Timezone", _TIMEZONE_KEYS),
        ("Status", _STATUS_KEYS),
        ("Owner", _OWNER_KEYS),
        ("Tags", _TAG_KEYS),
        ("URL", _URL_KEYS),
        ("ID", _ID_KEYS),
    ):
        value = _first_key(item, keys)
        if _non_empty(value):
            lines.append(f"- {label}: {_compact_list(value)}")

    # Add a few scalar fields that were not covered by common groups.  This
    # keeps the renderer useful for arbitrary generated capabilities while
    # avoiding raw JSON dumps in user mode.
    covered = set(_TITLE_KEYS + _DESCRIPTION_KEYS + _START_KEYS + _END_KEYS + _ID_KEYS + _LOCATION_KEYS + _TIMEZONE_KEYS + _STATUS_KEYS + _OWNER_KEYS + _URL_KEYS + _TAG_KEYS)
    extra_count = 0
    for key, value in item.items():
        if key in covered or key.startswith("_") or not _non_empty(value):
            continue
        if isinstance(value, (str, int, float, bool)):
            lines.append(f"- {key}: {_short_value(value)}")
            extra_count += 1
        if extra_count >= 3:
            break
    return lines


def _render_record(item: dict[str, Any], idx: int) -> list[str]:
    lines = [f"{idx}. {_item_title(item, idx)}"]
    lines.extend(_item_detail_lines(item))
    return lines


def _structural_summary(body: Any) -> list[str]:
    """Generic summary from common runtime output shapes.

    The renderer is intentionally capability-agnostic. It extracts the fields
    most often useful to humans across domains: title/name, description/body,
    time/date, location, status, owner/user, tags, URL, ID, count, and affected
    count. Detailed JSON stays behind Advanced/Developer/Diagnostic profiles.
    """
    lines: list[str] = []

    if isinstance(body, list):
        lines.append(f"Result count: {len(body)}")
        for idx, item in enumerate(body[:8], 1):
            if isinstance(item, dict):
                lines.extend(_render_record(item, idx))
            else:
                lines.append(f"{idx}. {_short_value(item)}")
        return lines

    if not isinstance(body, dict):
        if body not in (None, ""):
            return [f"Result: {_short_value(body)}"]
        return []

    for key in ("operation", "success", "affected_count"):
        if key in body and _non_empty(body.get(key)):
            label = key.replace("_", " ").title()
            lines.append(f"{label}: {_short_value(body.get(key))}")

    result = body.get("result")
    if isinstance(result, list):
        lines.append(f"Result count: {len(result)}")
        for idx, item in enumerate(result[:8], 1):
            if isinstance(item, dict):
                lines.extend(_render_record(item, idx))
            else:
                lines.append(f"{idx}. {_short_value(item)}")
    elif isinstance(result, dict):
        lines.extend(_render_record(result, 1))
    elif _non_empty(result):
        lines.append(f"Result: {_short_value(result)}")

    if "result" not in body and not any(line.startswith("1. ") for line in lines):
        # Body itself may be a single record.
        record_lines = _render_record(body, 1)
        if len(record_lines) > 1 or _first_key(body, _TITLE_KEYS + _ID_KEYS):
            lines.extend(record_lines)

    # If still empty, show stable scalar fields only.
    if not lines:
        shown = 0
        for key, value in body.items():
            if key.startswith("_") or not _non_empty(value):
                continue
            if isinstance(value, (str, int, float, bool)):
                lines.append(f"{key}: {_short_value(value)}")
                shown += 1
            if shown >= 6:
                break
    return lines


def _extract_text_answer(payload: dict[str, Any]) -> str:
    for key in ("final_answer", "message", "answer", "summary"):
        value = str(payload.get(key) or "").strip()
        if value and value.lower() not in _BLOCKED and not value.endswith(".json"):
            return value
    return ""


def render_runtime_response(payload: Any, *, profile: str = "user") -> str:
    """Render runtime output through presentation profiles.

    Profiles are generic display levels:
    - user: concise answer with high-value result fields
    - advanced: useful runtime summary plus collapsible structured result
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
            elif err:
                msg = str(err)
        msg = msg or "Runtime execution failed."
        if profile == "advanced":
            return f"{_status_icon(False, status)} Runtime execution failed.\n\n{msg}\n\n```json\n{_safe_json(body)}\n```"
        return f"{_status_icon(False, status)} {msg}"

    lines = _structural_summary(body)
    text = _extract_text_answer(payload)

    if profile == "advanced":
        head = f"{_status_icon(True, status)} Runtime execution completed."
        if tool_id:
            head += f"\n\nTool: `{tool_id}`"
        if lines:
            head += "\n\n" + "\n".join(lines)
        elif text:
            head += "\n\n" + text
        head += "\n\n<details><summary>Structured result</summary>\n\n```json\n" + _safe_json(body) + "\n```\n</details>"
        return head

    # User profile: concise, no diagnostic block. English labels are neutral UI
    # labels, not business-specific or locale-specific generated content.
    if lines:
        return f"{_status_icon(True, status)} Runtime execution completed.\n\n" + "\n".join(lines)
    return text or f"{_status_icon(True, status)} Runtime execution completed."
