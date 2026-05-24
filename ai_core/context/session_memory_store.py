from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ai_core.config.paths import RUNTIME_SESSIONS


@dataclass
class ContextWindow:
    session_id: str
    recent_turns: list[dict[str, Any]]
    rolling_summary: str
    open_items: list[str]
    boundary: dict[str, Any]


class SessionMemoryStore:
    """Generic conversation/session persistence.

    Durable structured state is written locally and, when configured, mirrored
    to Postgres.  This class stores runtime-neutral records only: sessions,
    turns, summaries, feedback, and promoted memory candidates.
    """

    def __init__(self, *, root: Path | None = None) -> None:
        self.root = root or RUNTIME_SESSIONS
        self.root.mkdir(parents=True, exist_ok=True)
        self.sqlite_path = self.root / "session_memory.sqlite3"
        self._init_sqlite()
        self._init_postgres_if_available()

    def start_or_get_session(self, session_id: str | None = None, *, metadata: dict[str, Any] | None = None) -> str:
        sid = str(session_id or "").strip() or "session_" + uuid4().hex[:16]
        now = self._now()
        meta = metadata or {}
        with sqlite3.connect(self.sqlite_path) as con:
            con.execute(
                """
                insert into sessions(session_id, created_at, updated_at, metadata_json)
                values(?, ?, ?, ?)
                on conflict(session_id) do update set updated_at=excluded.updated_at
                """,
                (sid, now, now, json.dumps(meta, ensure_ascii=False)),
            )
        self._pg_execute(
            """
            insert into sessions(session_id, created_at, updated_at, metadata_json)
            values(%s, %s, %s, %s)
            on conflict(session_id) do update set updated_at=excluded.updated_at
            """,
            (sid, now, now, json.dumps(meta, ensure_ascii=False)),
        )
        return sid

    def append_turn(
        self,
        *,
        session_id: str,
        run_id: str,
        user_input: str,
        final_answer: str,
        stage_results: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = self._now()
        record = {
            "turn_id": "turn_" + uuid4().hex[:16],
            "session_id": session_id,
            "run_id": run_id,
            "user_input": str(user_input or ""),
            "final_answer": str(final_answer or ""),
            "stage_results": stage_results or {},
            "metadata": metadata or {},
            "created_at": now,
        }
        with sqlite3.connect(self.sqlite_path) as con:
            con.execute(
                """
                insert into turns(turn_id, session_id, run_id, user_input, final_answer, stage_results_json, metadata_json, created_at)
                values(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["turn_id"], session_id, run_id, record["user_input"], record["final_answer"],
                    json.dumps(record["stage_results"], ensure_ascii=False),
                    json.dumps(record["metadata"], ensure_ascii=False), now,
                ),
            )
            con.execute("update sessions set updated_at=? where session_id=?", (now, session_id))
        self._pg_execute(
            """
            insert into turns(turn_id, session_id, run_id, user_input, final_answer, stage_results_json, metadata_json, created_at)
            values(%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                record["turn_id"], session_id, run_id, record["user_input"], record["final_answer"],
                json.dumps(record["stage_results"], ensure_ascii=False),
                json.dumps(record["metadata"], ensure_ascii=False), now,
            ),
        )
        self._append_jsonl("turns.jsonl", record)
        return record

    def load_context_window(self, session_id: str, *, limit: int = 8) -> ContextWindow:
        with sqlite3.connect(self.sqlite_path) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "select * from turns where session_id=? order by created_at desc limit ?",
                (session_id, int(limit)),
            ).fetchall()
            summary_row = con.execute(
                "select summary_text, open_items_json from session_summaries where session_id=? order by created_at desc limit 1",
                (session_id,),
            ).fetchone()
        recent = []
        for row in reversed(rows):
            recent.append({
                "turn_id": row["turn_id"],
                "run_id": row["run_id"],
                "user_input": row["user_input"],
                "final_answer": row["final_answer"],
                "created_at": row["created_at"],
            })
        rolling_summary = ""
        open_items: list[str] = []
        if summary_row:
            rolling_summary = str(summary_row["summary_text"] or "")
            try:
                parsed = json.loads(summary_row["open_items_json"] or "[]")
                if isinstance(parsed, list):
                    open_items = [str(x) for x in parsed if str(x).strip()]
            except Exception:
                open_items = []
        boundary = self.boundary_status(session_id)
        return ContextWindow(session_id=session_id, recent_turns=recent, rolling_summary=rolling_summary, open_items=open_items, boundary=boundary)

    def save_summary(self, *, session_id: str, summary_text: str, open_items: list[str] | None = None, source_run_id: str | None = None) -> None:
        now = self._now()
        summary_id = "summary_" + uuid4().hex[:16]
        payload = json.dumps(open_items or [], ensure_ascii=False)
        with sqlite3.connect(self.sqlite_path) as con:
            con.execute(
                "insert into session_summaries(summary_id, session_id, source_run_id, summary_text, open_items_json, created_at) values(?, ?, ?, ?, ?, ?)",
                (summary_id, session_id, source_run_id or "", summary_text, payload, now),
            )
        self._pg_execute(
            "insert into session_summaries(summary_id, session_id, source_run_id, summary_text, open_items_json, created_at) values(%s, %s, %s, %s, %s, %s)",
            (summary_id, session_id, source_run_id or "", summary_text, payload, now),
        )
        self._append_jsonl("summaries.jsonl", {
            "summary_id": summary_id,
            "session_id": session_id,
            "source_run_id": source_run_id,
            "summary_text": summary_text,
            "open_items": open_items or [],
            "created_at": now,
        })

    def record_feedback(self, *, session_id: str, run_id: str, rating: str, note: str = "") -> dict[str, Any]:
        now = self._now()
        record = {
            "feedback_id": "feedback_" + uuid4().hex[:16],
            "session_id": session_id,
            "run_id": run_id,
            "rating": str(rating or "").strip().lower(),
            "note": str(note or ""),
            "created_at": now,
        }
        with sqlite3.connect(self.sqlite_path) as con:
            con.execute(
                "insert into feedback(feedback_id, session_id, run_id, rating, note, created_at) values(?, ?, ?, ?, ?, ?)",
                (record["feedback_id"], session_id, run_id, record["rating"], record["note"], now),
            )
        self._pg_execute(
            "insert into feedback(feedback_id, session_id, run_id, rating, note, created_at) values(%s, %s, %s, %s, %s, %s)",
            (record["feedback_id"], session_id, run_id, record["rating"], record["note"], now),
        )
        self._append_jsonl("feedback.jsonl", record)
        return record

    def boundary_status(self, session_id: str, *, soft_turn_limit: int = 30, hard_turn_limit: int = 50) -> dict[str, Any]:
        with sqlite3.connect(self.sqlite_path) as con:
            count = con.execute("select count(*) from turns where session_id=?", (session_id,)).fetchone()[0]
        return {
            "turn_count": int(count),
            "soft_limit": int(soft_turn_limit),
            "hard_limit": int(hard_turn_limit),
            "should_suggest_new_session": int(count) >= int(soft_turn_limit),
            "should_require_new_session": int(count) >= int(hard_turn_limit),
        }


    def list_sessions(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """Return recently active sessions for UI navigation.

        The returned payload is intentionally generic and contains no
        domain-specific assumptions.  Titles are derived from explicit metadata
        first, then from the latest user input, and finally from the session id.
        """
        with sqlite3.connect(self.sqlite_path) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                """
                select s.session_id, s.created_at, s.updated_at, s.metadata_json,
                       (select count(*) from turns t where t.session_id=s.session_id) as turn_count,
                       (select user_input from turns t where t.session_id=s.session_id order by t.created_at desc limit 1) as latest_input,
                       (select final_answer from turns t where t.session_id=s.session_id order by t.created_at desc limit 1) as latest_answer
                  from sessions s
                 order by s.updated_at desc
                 limit ?
                """,
                (int(limit),),
            ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            try:
                meta = json.loads(row["metadata_json"] or "{}")
                if not isinstance(meta, dict):
                    meta = {}
            except Exception:
                meta = {}
            title = str(meta.get("title") or row["latest_input"] or row["session_id"]).strip()
            if len(title) > 80:
                title = title[:77] + "..."
            boundary = self.boundary_status(str(row["session_id"]))
            items.append({
                "session_id": row["session_id"],
                "title": title,
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "turn_count": int(row["turn_count"] or 0),
                "latest_input": row["latest_input"] or "",
                "latest_answer": row["latest_answer"] or "",
                "metadata": meta,
                "boundary": boundary,
            })
        return items

    def get_session_snapshot(self, session_id: str, *, limit: int = 20) -> dict[str, Any]:
        sid = self.start_or_get_session(session_id)
        window = self.load_context_window(sid, limit=limit)
        return {
            "session_id": sid,
            "recent_turns": window.recent_turns,
            "rolling_summary": window.rolling_summary,
            "open_items": window.open_items,
            "boundary": window.boundary,
        }

    def rename_session(self, session_id: str, title: str) -> dict[str, Any]:
        sid = self.start_or_get_session(session_id)
        now = self._now()
        with sqlite3.connect(self.sqlite_path) as con:
            row = con.execute("select metadata_json from sessions where session_id=?", (sid,)).fetchone()
            try:
                meta = json.loads((row[0] if row else "{}") or "{}")
                if not isinstance(meta, dict):
                    meta = {}
            except Exception:
                meta = {}
            meta["title"] = str(title or "").strip()
            con.execute("update sessions set metadata_json=?, updated_at=? where session_id=?", (json.dumps(meta, ensure_ascii=False), now, sid))
        return {"session_id": sid, "title": str(title or "").strip(), "updated_at": now}

    def _init_sqlite(self) -> None:
        with sqlite3.connect(self.sqlite_path) as con:
            con.executescript(
                """
                create table if not exists sessions(
                    session_id text primary key,
                    created_at text not null,
                    updated_at text not null,
                    metadata_json text not null default '{}'
                );
                create table if not exists turns(
                    turn_id text primary key,
                    session_id text not null,
                    run_id text not null,
                    user_input text not null,
                    final_answer text not null,
                    stage_results_json text not null,
                    metadata_json text not null,
                    created_at text not null
                );
                create index if not exists idx_turns_session_created on turns(session_id, created_at);
                create table if not exists session_summaries(
                    summary_id text primary key,
                    session_id text not null,
                    source_run_id text not null,
                    summary_text text not null,
                    open_items_json text not null,
                    created_at text not null
                );
                create table if not exists feedback(
                    feedback_id text primary key,
                    session_id text not null,
                    run_id text not null,
                    rating text not null,
                    note text not null,
                    created_at text not null
                );
                """
            )

    def _init_postgres_if_available(self) -> None:
        self.pg_dsn = os.getenv("RUNTIME_POSTGRES_DSN") or os.getenv("DATABASE_URL") or ""
        if not self.pg_dsn:
            return
        ddl = """
        create table if not exists sessions(
            session_id text primary key,
            created_at text not null,
            updated_at text not null,
            metadata_json jsonb not null default '{}'::jsonb
        );
        create table if not exists turns(
            turn_id text primary key,
            session_id text not null,
            run_id text not null,
            user_input text not null,
            final_answer text not null,
            stage_results_json jsonb not null,
            metadata_json jsonb not null,
            created_at text not null
        );
        create index if not exists idx_turns_session_created on turns(session_id, created_at);
        create table if not exists session_summaries(
            summary_id text primary key,
            session_id text not null,
            source_run_id text not null,
            summary_text text not null,
            open_items_json jsonb not null,
            created_at text not null
        );
        create table if not exists feedback(
            feedback_id text primary key,
            session_id text not null,
            run_id text not null,
            rating text not null,
            note text not null,
            created_at text not null
        );
        """
        self._pg_execute(ddl, None)

    def _pg_execute(self, sql: str, params: tuple[Any, ...] | None) -> None:
        dsn = getattr(self, "pg_dsn", "")
        if not dsn:
            return
        try:
            import psycopg  # type: ignore
            with psycopg.connect(dsn) as con:
                with con.cursor() as cur:
                    cur.execute(sql, params)
                con.commit()
        except Exception:
            return

    def _append_jsonl(self, name: str, record: dict[str, Any]) -> None:
        path = self.root / name
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
