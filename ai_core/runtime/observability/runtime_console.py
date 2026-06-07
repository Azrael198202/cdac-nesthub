from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_core.config.paths import PROJECT_ROOT


RUNTIME_ROOT = PROJECT_ROOT / "runtime"
CONSOLE_LOG = RUNTIME_ROOT / "logs" / "runtime_console.jsonl"


def emit_console_event(*, area: str, event: str, status: str = "info", message: str = "", data: dict[str, Any] | None = None) -> None:
    """Append an operator-visible runtime console event.

    This is observability only.  It does not affect execution semantics and it
    must not contain secrets.  Callers should pass only public status material,
    command names, file paths, short stderr tails, and runtime stage metadata.
    """
    try:
        CONSOLE_LOG.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "area": str(area or "runtime"),
            "event": str(event or "event"),
            "status": str(status or "info"),
            "message": _redact(str(message or ""))[-4000:],
            "data": _redact_data(data or {}),
        }
        with CONSOLE_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        return


def list_console_sources() -> list[dict[str, Any]]:
    # Phase-1 console scope is intentionally narrow and stable.
    # Only operator logs and traces are scanned; runtime artifacts, external
    # runtimes, downloads, caches, datasets, generated tools, and generated
    # models are excluded to avoid UI stalls and backend reload loops.
    roots = [
        RUNTIME_ROOT / "logs",
        RUNTIME_ROOT / "traces",
    ]
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for pattern in ("*.jsonl", "*.log", "*.txt", "*.json"):
            files.extend(root.rglob(pattern))
    unique: dict[str, Path] = {}
    for p in files:
        try:
            if p.is_file():
                rel = p.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
                unique[rel] = p
        except Exception:
            continue
    out: list[dict[str, Any]] = []
    for rel, p in sorted(unique.items()):
        try:
            stat = p.stat()
            out.append({
                "id": rel,
                "path": rel,
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                "type": _source_type(p),
            })
        except Exception:
            continue
    return out


def read_console_source(source: str | None, *, cursor: int = 0, limit_bytes: int = 65536, tail: bool = False) -> dict[str, Any]:
    source = source or "runtime/logs/runtime_console.jsonl"
    path = _safe_source_path(source)
    if path is None or not path.exists() or not path.is_file():
        return {"ok": False, "status": "not_found", "source": source, "cursor": cursor, "next_cursor": cursor, "content": ""}
    size = path.stat().st_size
    if tail:
        cursor = max(0, size - limit_bytes)
    else:
        cursor = max(0, min(int(cursor or 0), size))
    with path.open("rb") as fh:
        fh.seek(cursor)
        raw = fh.read(max(1024, min(int(limit_bytes or 65536), 262144)))
        next_cursor = fh.tell()
    text = raw.decode("utf-8", errors="replace")
    return {
        "ok": True,
        "status": "completed",
        "source": path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix(),
        "cursor": cursor,
        "next_cursor": next_cursor,
        "size_bytes": size,
        "content": _redact(text),
        "modified_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
    }


def _safe_source_path(source: str) -> Path | None:
    value = str(source or "").strip().lstrip("/")
    if not value:
        value = "runtime/logs/runtime_console.jsonl"
    path = (PROJECT_ROOT / value).resolve()
    allowed = [
        (RUNTIME_ROOT / "logs").resolve(),
        (RUNTIME_ROOT / "traces").resolve(),
    ]
    try:
        if not any(path.is_relative_to(root) for root in allowed):
            return None
    except AttributeError:
        if not any(str(path).startswith(str(root) + os.sep) or path == root for root in allowed):
            return None
    return path


def _source_type(path: Path) -> str:
    text = path.as_posix().lower()
    if "trace" in text:
        return "trace"
    if "error" in text:
        return "error"
    if path.suffix == ".jsonl":
        return "stream"
    return "file"


def _redact_data(data: Any) -> Any:
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            key = str(k)
            if any(s in key.casefold() for s in ("secret", "password", "token", "apikey", "api_key", "authorization")):
                out[key] = "***REDACTED***"
            else:
                out[key] = _redact_data(v)
        return out
    if isinstance(data, list):
        return [_redact_data(x) for x in data[:200]]
    if isinstance(data, str):
        return _redact(data)
    return data


def _redact(text: str) -> str:
    if not text:
        return text
    import re
    patterns = [
        r"(?i)(password|secret|token|api[_-]?key|authorization)(\s*[:=]\s*)([^\s,;]+)",
        r"(?i)(bearer\s+)[A-Za-z0-9._\-]+",
    ]
    out = text
    for pat in patterns:
        out = re.sub(pat, lambda m: (m.group(1) + m.group(2) + "***REDACTED***") if len(m.groups()) >= 2 else m.group(1) + "***REDACTED***", out)
    return out
