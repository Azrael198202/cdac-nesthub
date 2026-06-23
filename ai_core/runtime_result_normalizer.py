from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


_TEXT_KEYS = ("final_answer", "message", "answer", "text", "summary")
_PAYLOAD_KEYS = ("result", "output", "tool_result", "workflow_results", "data", "payload")


def _read_json(path: Path) -> Any | None:
    try:
        if path.exists() and path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return None


def _is_delivery_path(value: str) -> bool:
    normalized = value.replace("\\", "/")
    return normalized.endswith(".json") and "/deliveries/" in normalized or normalized.startswith("runtime/deliveries/")


def _load_delivery_if_needed(value: Any, runtime_root: str | Path | None = None) -> Any:
    if not isinstance(value, str) or not _is_delivery_path(value):
        return value
    candidates: list[Path] = []
    p = Path(value)
    candidates.append(p)
    if runtime_root:
        root = Path(runtime_root)
        candidates.append(root / value)
        if value.startswith("runtime/"):
            candidates.append(root / value[len("runtime/"):])
    for candidate in candidates:
        loaded = _read_json(candidate)
        if loaded is not None:
            return loaded
    return value


def _find_text(payload: Any, runtime_root: str | Path | None = None, max_depth: int = 8) -> str | None:
    payload = _load_delivery_if_needed(payload, runtime_root)
    if max_depth <= 0:
        return None
    if isinstance(payload, str):
        if payload.strip() and payload.strip().lower() not in {"completed", "success", "ok"}:
            return payload
        return None
    if isinstance(payload, Mapping):
        for key in _TEXT_KEYS:
            value = payload.get(key)
            if isinstance(value, str) and value.strip() and value.strip().lower() not in {"completed", "success", "ok"}:
                return value
        for key in _PAYLOAD_KEYS:
            if key in payload:
                found = _find_text(payload[key], runtime_root, max_depth - 1)
                if found:
                    return found
        # Generic deep search, but keep deterministic order.
        for key, value in payload.items():
            if key in {"status", "action", "run_id", "job_id"}:
                continue
            found = _find_text(value, runtime_root, max_depth - 1)
            if found:
                return found
    if isinstance(payload, list):
        for item in payload:
            found = _find_text(item, runtime_root, max_depth - 1)
            if found:
                return found
    return None


def _find_structured_result(payload: Any, runtime_root: str | Path | None = None, max_depth: int = 8) -> Any | None:
    payload = _load_delivery_if_needed(payload, runtime_root)
    if max_depth <= 0:
        return None
    if isinstance(payload, Mapping):
        # Prefer concrete execution objects over wrapper status objects.
        for key in ("tool_result", "workflow_results", "result", "output", "data", "payload"):
            if key in payload:
                value = _load_delivery_if_needed(payload[key], runtime_root)
                if isinstance(value, Mapping) and set(value.keys()) - {"status", "action", "run_id"}:
                    return value
                nested = _find_structured_result(value, runtime_root, max_depth - 1)
                if nested is not None:
                    return nested
    return None


def normalize_runtime_response(payload: Any, *, runtime_root: str | Path | None = None, run_id: str | None = None) -> dict[str, Any]:
    """Return a user-visible async/runtime response.

    This prevents UI/API callers from showing only ``completed`` when the real answer
    is nested under final_answer/message/result/output or stored in a delivery JSON.
    """
    visible_text = _find_text(payload, runtime_root)
    structured = _find_structured_result(payload, runtime_root)
    status = "completed"
    if isinstance(payload, Mapping):
        status = str(payload.get("status") or status)
        run_id = run_id or payload.get("run_id") or payload.get("job_id")

    if visible_text:
        return {
            "status": status,
            "run_id": run_id,
            "message": visible_text,
            "final_answer": visible_text,
            "result": structured if structured is not None else payload,
        }

    if structured is not None:
        return {
            "status": status,
            "run_id": run_id,
            "message": json.dumps(structured, ensure_ascii=False, indent=2),
            "final_answer": json.dumps(structured, ensure_ascii=False, indent=2),
            "result": structured,
        }

    # Last resort: keep payload visible for diagnostics instead of returning only completed.
    if isinstance(payload, Mapping) and set(payload.keys()) <= {"status", "action", "run_id"}:
        return {
            "status": status,
            "run_id": run_id,
            "message": "Runtime completed, but no user-visible result was attached. Check final_synthesis/job.result trace.",
            "final_answer": "Runtime completed, but no user-visible result was attached. Check final_synthesis/job.result trace.",
            "result": payload,
            "diagnostic_code": "completed_without_visible_result",
        }
    return {"status": status, "run_id": run_id, "message": str(payload), "final_answer": str(payload), "result": payload}
