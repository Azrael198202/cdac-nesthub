from __future__ import annotations

from copy import deepcopy
from typing import Any


def get_path(data: Any, path: str, default: Any = None) -> Any:
    if not path:
        return data
    cur = data
    for part in _parts(path):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return default
    return cur


def set_path(data: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    root = deepcopy(data)
    if not path:
        if isinstance(value, dict):
            return value
        return root
    cur: Any = root
    parts = _parts(path)
    for part in parts[:-1]:
        if isinstance(cur, dict):
            cur = cur.setdefault(part, {})
        else:
            return root
    if isinstance(cur, dict):
        cur[parts[-1]] = value
    return root


def _parts(path: str) -> list[str]:
    path = path.strip().strip("$").strip(".")
    if not path:
        return []
    return [p for p in path.replace("[", ".").replace("]", "").split(".") if p]
