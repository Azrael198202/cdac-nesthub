from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

_TEXT_KEYS = ("final_answer", "message", "answer", "text", "summary", "answer_material", "generated_content", "final_content", "content", "stdout")
_PAYLOAD_KEYS = ("result", "output", "tool_result", "workflow_results", "data", "payload", "synthesis", "delivery", "presentation", "execution", "runtime_output")
_BLOCKED_TEXT = {"", "completed", "success", "ok", "conversation_message", "runtime_response", "async job completed", "async job completed.", "completed_with_no_participant_result", "partial_failed", "no_usable_result", "failed"}


def _read_json(path: Path) -> Any | None:
    try:
        if path.exists() and path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return None


def _is_delivery_path(value: str) -> bool:
    normalized = value.strip().replace("\\", "/")
    return normalized.endswith(".json") and ("/deliveries/" in normalized or normalized.startswith("deliveries/") or normalized.startswith("runtime/deliveries/"))


def _candidate_paths(value: str, runtime_root: str | Path | None = None) -> list[Path]:
    normalized = value.strip().replace("\\", "/")
    paths = [Path(normalized)]
    if runtime_root:
        root = Path(runtime_root)
        paths.append(root / normalized)
        if normalized.startswith("runtime/"):
            paths.append(root / normalized[len("runtime/"):])
        if normalized.startswith("deliveries/"):
            paths.append(root / normalized)
    return paths


def _load_delivery_if_needed(value: Any, runtime_root: str | Path | None = None) -> Any:
    if not isinstance(value, str) or not _is_delivery_path(value):
        return value
    for candidate in _candidate_paths(value, runtime_root):
        loaded = _read_json(candidate)
        if loaded is not None:
            return loaded
    return value


def _safe_text(value: Any) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        if text.casefold() in _BLOCKED_TEXT:
            return None
        if _is_delivery_path(text):
            return None
        return text or None
    if isinstance(value, (int, float, bool)):
        return str(value)
    return None


def _find_text(payload: Any, runtime_root: str | Path | None = None, max_depth: int = 9) -> str | None:
    payload = _load_delivery_if_needed(payload, runtime_root)
    if max_depth <= 0:
        return None
    text = _safe_text(payload)
    if text:
        return text
    if isinstance(payload, Mapping):
        # Transport-only wrappers are not visible answers.
        if set(payload.keys()) <= {"status", "action", "run_id", "job_id", "runtime_state"}:
            return None
        for key in _TEXT_KEYS:
            if key in payload:
                found = _find_text(payload.get(key), runtime_root, max_depth - 1)
                if found:
                    return found
        for key in _PAYLOAD_KEYS:
            if key in payload:
                found = _find_text(payload.get(key), runtime_root, max_depth - 1)
                if found:
                    return found
        internal_keys = {"status", "synthesis_mode", "task_name", "llm_used", "replanned", "delivery_id", "origin", "upstream_origin", "created_at", "run_id", "job_id"}
        for key, value in payload.items():
            if str(key) in internal_keys:
                continue
            found = _find_text(value, runtime_root, max_depth - 1)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _find_text(item, runtime_root, max_depth - 1)
            if found:
                return found
    return None


def _find_structured_result(payload: Any, runtime_root: str | Path | None = None, max_depth: int = 9) -> Any | None:
    payload = _load_delivery_if_needed(payload, runtime_root)
    if max_depth <= 0:
        return None
    if isinstance(payload, Mapping):
        # Prefer concrete capability/tool result objects.
        for key in ("tool_result", "workflow_results", "result", "output", "data", "payload", "synthesis"):
            if key in payload:
                value = _load_delivery_if_needed(payload[key], runtime_root)
                if isinstance(value, Mapping) and set(value.keys()) - {"status", "action", "run_id", "job_id", "synthesis_mode", "task_name", "llm_used", "replanned", "final_answer", "message"}:
                    return value
                nested = _find_structured_result(value, runtime_root, max_depth - 1)
                if nested is not None:
                    return nested
        public_keys = set(payload.keys()) - {"status", "action", "run_id", "job_id", "runtime_state", "synthesis_mode", "task_name", "llm_used", "replanned", "delivery_id", "origin", "upstream_origin", "created_at", "final_answer", "message"}
        if public_keys:
            return dict(payload)
    elif isinstance(payload, list) and payload:
        return payload
    return None


def normalize_runtime_response(payload: Any, *, runtime_root: str | Path | None = None, run_id: str | None = None) -> dict[str, Any]:
    """Normalize runtime/async output into a user-visible response.

    The runtime may finish with transport-only values such as ``completed`` or a
    persisted delivery JSON path. This function expands delivery files and finds
    the real public result without knowing any capability-specific business name.
    """
    loaded = _load_delivery_if_needed(payload, runtime_root)
    visible_text = _find_text(loaded, runtime_root)
    structured = _find_structured_result(loaded, runtime_root)
    status = "completed"
    if isinstance(loaded, Mapping):
        status = str(loaded.get("status") or (loaded.get("synthesis") or {}).get("status") if isinstance(loaded.get("synthesis"), Mapping) else "completed")
        run_id = run_id or loaded.get("run_id") or loaded.get("job_id")
    elif isinstance(payload, Mapping):
        status = str(payload.get("status") or status)
        run_id = run_id or payload.get("run_id") or payload.get("job_id")

    if visible_text:
        return {"status": status, "run_id": run_id, "message": visible_text, "final_answer": visible_text, "result": structured if structured is not None else loaded}

    no_visible_statuses = {"completed_with_no_participant_result", "partial_failed", "no_usable_result"}
    if str(status).strip().casefold() in no_visible_statuses:
        diagnostic = "Runtime completed but produced no participant/tool result. Check task graph participant selection and execution trace."
        return {"status": status, "run_id": run_id, "message": diagnostic, "final_answer": diagnostic, "result": loaded, "diagnostic_code": "delivery_without_visible_result"}

    if structured is not None:
        message = json.dumps(structured, ensure_ascii=False, indent=2)
        return {"status": status, "run_id": run_id, "message": message, "final_answer": message, "result": structured}
    return {
        "status": status,
        "run_id": run_id,
        "message": "Runtime completed, but no user-visible result was attached. Check final_synthesis/job.result trace.",
        "final_answer": "Runtime completed, but no user-visible result was attached. Check final_synthesis/job.result trace.",
        "result": loaded,
        "diagnostic_code": "completed_without_visible_result",
    }
