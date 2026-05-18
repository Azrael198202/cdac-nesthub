from __future__ import annotations

from uuid import uuid4


def new_id(prefix: str) -> str:
    safe_prefix = "".join(ch for ch in prefix.lower() if ch.isalnum() or ch == "_").strip("_") or "item"
    return f"{safe_prefix}_{uuid4().hex[:8]}"
