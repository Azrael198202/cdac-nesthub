from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

_JSON_PRIMITIVE = (str, int, float, bool, type(None))


def make_json_safe(value: Any, *, max_depth: int = 30, max_items: int = 2000) -> Any:
    """Return a JSON-serializable copy of *value*.

    This helper is intentionally generic and domain-neutral. It prevents runtime
    crashes caused by circular references, Path objects, exceptions, functions,
    modules, dataclasses, sets, bytes, and other non-JSON values before data is
    emitted to SSE, written to traces, or returned from sandbox runners.
    """
    seen: set[int] = set()

    def convert(obj: Any, depth: int) -> Any:
        if isinstance(obj, _JSON_PRIMITIVE):
            return obj
        if depth > max_depth:
            return {"__truncated__": "max_depth_exceeded", "type": type(obj).__name__}

        obj_id = id(obj)
        if isinstance(obj, (dict, list, tuple, set, frozenset)) or dataclasses.is_dataclass(obj):
            if obj_id in seen:
                return {"__circular_reference__": True, "type": type(obj).__name__}
            seen.add(obj_id)
            try:
                if dataclasses.is_dataclass(obj):
                    return convert(dataclasses.asdict(obj), depth + 1)
                if isinstance(obj, dict):
                    out: dict[str, Any] = {}
                    for index, (key, item) in enumerate(obj.items()):
                        if index >= max_items:
                            out["__truncated_items__"] = len(obj) - max_items
                            break
                        if isinstance(key, _JSON_PRIMITIVE):
                            safe_key = str(key)
                        else:
                            safe_key = repr(key)
                        out[safe_key] = convert(item, depth + 1)
                    return out
                seq = list(obj)
                out_list = [convert(item, depth + 1) for item in seq[:max_items]]
                if len(seq) > max_items:
                    out_list.append({"__truncated_items__": len(seq) - max_items})
                return out_list
            finally:
                seen.discard(obj_id)

        if isinstance(obj, Path):
            return str(obj)
        if isinstance(obj, bytes):
            try:
                return obj.decode("utf-8")
            except Exception:
                return {"__bytes__": len(obj)}
        if isinstance(obj, BaseException):
            return {"error_type": type(obj).__name__, "message": str(obj)}
        if callable(obj):
            return {"__callable__": getattr(obj, "__name__", type(obj).__name__)}

        try:
            json.dumps(obj)
            return obj
        except Exception:
            return repr(obj)

    return convert(value, 0)


def safe_json_dumps(value: Any, **kwargs: Any) -> str:
    kwargs.setdefault("ensure_ascii", False)
    return json.dumps(make_json_safe(value), **kwargs)
