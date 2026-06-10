from __future__ import annotations

from uuid import uuid4


def new_id(prefix: str = "id") -> str:
    """Return a compact runtime identifier.

    This helper is intentionally generic and belongs to the auxiliary runtime
    framework. It is exported from the runtime package so callers can use
    ``from auxiliary_brain.runtime import new_id`` without colliding with the
    runtime package directory.
    """
    clean = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in str(prefix or "id"))
    clean = clean.strip("_") or "id"
    return f"{clean}_{uuid4().hex[:12]}"


__all__ = ["new_id"]
