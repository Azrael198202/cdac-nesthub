#!/usr/bin/env python3
"""Reset local test data for session and vector-memory tests.

This script removes runtime data created by conversation/session memory and the
local vector-memory store.  When a Postgres DSN is configured, it also truncates
only the runtime memory tables used by this project.

Environment variables:
  RUNTIME_POSTGRES_DSN or DATABASE_URL: optional Postgres connection string.
  RESET_RUNTIME_DATA_CONFIRM=YES: required unless --yes is passed.

Usage:
  python scripts/reset_runtime_data.py --yes
  python scripts/reset_runtime_data.py --yes --include-runtime-generated
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
SESSIONS = RUNTIME / "sessions"
KNOWLEDGE = RUNTIME / "knowledge"
VECTOR_MEMORY = KNOWLEDGE / "vector_memory"

SQLITE_TABLES = ("feedback", "session_summaries", "turns", "sessions")
REUSE_SQLITE_TABLES = ("reusable_assets", "short_answer_cache")
POSTGRES_TABLES = SQLITE_TABLES


def _safe_remove_path(path: Path) -> None:
    resolved = path.resolve()
    runtime_root = RUNTIME.resolve()
    if runtime_root not in resolved.parents and resolved != runtime_root:
        raise RuntimeError(f"Refusing to remove path outside runtime: {resolved}")
    if resolved.exists():
        if resolved.is_dir():
            shutil.rmtree(resolved)
        else:
            resolved.unlink()


def _reset_sqlite() -> None:
    db_path = SESSIONS / "session_memory.sqlite3"
    if db_path.exists():
        with sqlite3.connect(db_path) as con:
            for table in SQLITE_TABLES:
                try:
                    con.execute(f"delete from {table}")
                except sqlite3.OperationalError:
                    pass
            con.commit()
    reuse_path = SESSIONS / "execution_reuse.sqlite3"
    if reuse_path.exists():
        with sqlite3.connect(reuse_path) as con:
            for table in REUSE_SQLITE_TABLES:
                try:
                    con.execute(f"delete from {table}")
                except sqlite3.OperationalError:
                    pass
            con.commit()


def _reset_postgres() -> bool:
    dsn = os.getenv("RUNTIME_POSTGRES_DSN") or os.getenv("DATABASE_URL") or ""
    if not dsn:
        return False
    try:
        import psycopg  # type: ignore
    except Exception as exc:
        print(f"[postgres] skipped: psycopg is not available: {exc}")
        return False
    try:
        with psycopg.connect(dsn) as con:
            with con.cursor() as cur:
                cur.execute("truncate table feedback, session_summaries, turns, sessions restart identity cascade")
            con.commit()
        return True
    except Exception as exc:
        print(f"[postgres] skipped: {exc}")
        return False


def _reset_jsonl_files(paths: Iterable[Path]) -> None:
    for path in paths:
        if path.exists():
            path.write_text("", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="Confirm reset")
    parser.add_argument(
        "--include-runtime-generated",
        action="store_true",
        help="Also remove runtime generated artifacts, traces, checkpoints, and deliveries",
    )
    args = parser.parse_args()

    if not args.yes and os.getenv("RESET_RUNTIME_DATA_CONFIRM") != "YES":
        print("Refused. Pass --yes or set RESET_RUNTIME_DATA_CONFIRM=YES.")
        return 2

    RUNTIME.mkdir(exist_ok=True)
    SESSIONS.mkdir(parents=True, exist_ok=True)
    KNOWLEDGE.mkdir(parents=True, exist_ok=True)

    _reset_sqlite()
    _reset_jsonl_files([
        SESSIONS / "turns.jsonl",
        SESSIONS / "summaries.jsonl",
        SESSIONS / "feedback.jsonl",
        SESSIONS / "execution_assets.jsonl",
    ])
    _safe_remove_path(VECTOR_MEMORY)
    VECTOR_MEMORY.mkdir(parents=True, exist_ok=True)

    if args.include_runtime_generated:
        for name in ("generated", "traces", "checkpoints", "deliveries"):
            path = RUNTIME / name
            _safe_remove_path(path)
            path.mkdir(parents=True, exist_ok=True)

    pg_reset = _reset_postgres()
    print({
        "ok": True,
        "sqlite": str(SESSIONS / "session_memory.sqlite3"),
        "execution_reuse": str(SESSIONS / "execution_reuse.sqlite3"),
        "vector_memory": str(VECTOR_MEMORY),
        "postgres_reset": pg_reset,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
