from __future__ import annotations

from uuid import uuid4


def new_id(prefix: str = "id") -> str:
    """Return a compact runtime identifier.

    This helper is part of the auxiliary runtime framework, not a generated
    runtime artifact. It is intentionally domain-neutral.
    """
    clean = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in str(prefix or "id"))
    clean = clean.strip("_") or "id"
    return f"{clean}_{uuid4().hex[:12]}"
