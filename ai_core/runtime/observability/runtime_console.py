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
    roots = [
        RUNTIME_ROOT / "logs",
        RUNTIME_ROOT / "traces",
        RUNTIME_ROOT / "generated",
        RUNTIME_ROOT / "downloads",
        RUNTIME_ROOT / "external_runtimes",
        PROJECT_ROOT / "downloads",
        PROJECT_ROOT / "traces",
        PROJECT_ROOT / "generated",
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
        (PROJECT_ROOT / "runtime").resolve(),
        (PROJECT_ROOT / "downloads").resolve(),
        (PROJECT_ROOT / "traces").resolve(),
        (PROJECT_ROOT / "generated").resolve(),
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
    if "download" in text or "external_runtimes" in text:
        return "install_download"
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


def iter_console_events(*, source: str | None = None, cursor: int = 0, poll_interval: float = 1.0):
    """Yield Server-Sent Events from a safe runtime text source.

    This is a read-only operator stream. It tails runtime-owned files and emits
    normalized event payloads without changing workflow semantics.
    """
    source = source or "runtime/logs/runtime_console.jsonl"
    safe = _safe_source_path(source)
    if safe is None:
        payload = {"ts": datetime.now(timezone.utc).isoformat(), "level": "ERROR", "area": "RUNTIME", "event": "STREAM_SOURCE_REJECTED", "message": "Unsafe runtime console source"}
        yield f"event: runtime\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        return
    pos = max(0, int(cursor or 0))
    while True:
        try:
            if not safe.exists():
                time.sleep(max(0.2, float(poll_interval or 1.0)))
                continue
            size = safe.stat().st_size
            if pos > size:
                pos = 0
            with safe.open("rb") as fh:
                fh.seek(pos)
                raw = fh.read(65536)
                pos = fh.tell()
            if raw:
                text = _redact(raw.decode("utf-8", errors="replace"))
                for line in text.splitlines():
                    payload = _normalize_console_line(line, cursor=pos, source=source)
                    yield f"event: runtime\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            else:
                heartbeat = {"ts": datetime.now(timezone.utc).isoformat(), "level": "DEBUG", "area": "RUNTIME", "event": "HEARTBEAT", "message": ""}
                yield f": {json.dumps(heartbeat, ensure_ascii=False)}\n\n"
                time.sleep(max(0.2, float(poll_interval or 1.0)))
        except GeneratorExit:
            return
        except Exception as exc:
            payload = {"ts": datetime.now(timezone.utc).isoformat(), "level": "ERROR", "area": "RUNTIME", "event": "STREAM_ERROR", "message": str(exc)[:500]}
            yield f"event: runtime\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            time.sleep(max(0.5, float(poll_interval or 1.0)))


def _normalize_console_line(line: str, *, cursor: int, source: str) -> dict[str, Any]:
    try:
        obj = json.loads(line)
        if isinstance(obj, dict):
            status = str(obj.get("status") or obj.get("level") or "info").upper()
            return {
                "ts": obj.get("ts") or datetime.now(timezone.utc).isoformat(),
                "level": _status_to_level(status),
                "area": str(obj.get("area") or "RUNTIME").upper(),
                "event": str(obj.get("event") or obj.get("stage") or "EVENT").upper(),
                "message": str(obj.get("message") or ""),
                "data": _redact_data(obj.get("data") if isinstance(obj.get("data"), dict) else {}),
                "cursor": cursor,
                "source": source,
            }
    except Exception:
        pass
    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "level": "INFO",
        "area": "RUNTIME",
        "event": "RAW_LINE",
        "message": _redact(line),
        "cursor": cursor,
        "source": source,
    }


def _status_to_level(status: str) -> str:
    s = str(status or "").casefold()
    if any(x in s for x in ("fail", "error", "blocked", "rejected")):
        return "ERROR"
    if any(x in s for x in ("warn", "missing", "timeout", "repair")):
        return "WARN"
    if any(x in s for x in ("debug", "heartbeat")):
        return "DEBUG"
    return "INFO"


def list_runtime_explorer_tree(*, root: str = "runtime", max_entries: int = 500) -> dict[str, Any]:
    allowed_roots = {"runtime": RUNTIME_ROOT}
    base = allowed_roots.get(str(root or "runtime"), RUNTIME_ROOT).resolve()
    entries: list[dict[str, Any]] = []
    if not base.exists():
        return {"ok": True, "root": root, "entries": entries}
    for path in sorted(base.rglob("*")):
        if len(entries) >= max_entries:
            break
        try:
            rel = path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
            stat = path.stat()
            entries.append({
                "path": rel,
                "name": path.name,
                "type": "directory" if path.is_dir() else "file",
                "size_bytes": 0 if path.is_dir() else stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            })
        except Exception:
            continue
    return {"ok": True, "root": root, "entries": entries}


def resolve_runtime_explorer_file(path_value: str) -> Path | None:
    return _safe_source_path(path_value)
