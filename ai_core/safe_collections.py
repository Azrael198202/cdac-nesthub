from __future__ import annotations

import json
from typing import Any, Iterable


def safe_hashable(value: Any) -> Any:
    """Return a stable hashable representation for nested runtime values.

    Capability contracts may contain lists/dicts/nested lists. Creation pipelines
    must not put those raw values into set/frozenset keys. This helper preserves
    semantic equality without requiring callers to know the shape in advance.
    """
    if isinstance(value, dict):
        return tuple((str(k), safe_hashable(v)) for k, v in sorted(value.items(), key=lambda item: str(item[0])))
    if isinstance(value, (list, tuple)):
        return tuple(safe_hashable(v) for v in value)
    if isinstance(value, set):
        return tuple(sorted((safe_hashable(v) for v in value), key=lambda x: repr(x)))
    try:
        hash(value)
        return value
    except Exception:
        return repr(value)


def safe_json_key(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        return repr(safe_hashable(value))


def safe_dedupe(values: Iterable[Any] | Any, *, preserve_order: bool = True) -> list[Any]:
    if values is None:
        return []
    if isinstance(values, (str, bytes, dict)):
        iterable = [values]
    else:
        try:
            iterable = list(values)  # type: ignore[arg-type]
        except TypeError:
            iterable = [values]
    seen: set[Any] = set()
    out: list[Any] = []
    for item in iterable:
        key = safe_hashable(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    if not preserve_order:
        out.sort(key=lambda x: safe_json_key(x))
    return out


def safe_string_set(values: Iterable[Any] | Any) -> set[str]:
    return {str(v).strip() for v in safe_dedupe(values) if str(v).strip()}


def safe_string_list(values: Iterable[Any] | Any) -> list[str]:
    return [str(v).strip() for v in safe_dedupe(values) if str(v).strip()]
