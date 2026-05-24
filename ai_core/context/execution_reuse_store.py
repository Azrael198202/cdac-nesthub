from __future__ import annotations

import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ai_core.config.paths import RUNTIME_SESSIONS
from ai_core.runtime.environment.runtime_command_executor import RuntimeCommandExecutor


@dataclass
class ReuseDecision:
    reusable: bool
    reason: str
    asset: dict[str, Any] | None = None
    missing_inputs: list[dict[str, Any]] | None = None


class ExecutionReuseStore:
    """Durable execution reuse registry.

    This store is intentionally generic.  It records only reusable runtime
    assets and contracts that were proven by a completed execution: task name,
    selected agent ids, execution mode, parameter schema, generated or uploaded
    artifact paths, and a compact success summary.  It does not infer business
    meaning from names or task content.
    """

    def __init__(self, *, root: Path | None = None) -> None:
        self.root = root or RUNTIME_SESSIONS
        self.root.mkdir(parents=True, exist_ok=True)
        self.sqlite_path = self.root / "execution_reuse.sqlite3"
        self._init_sqlite()

    def register_success(
        self,
        *,
        task_graph: dict[str, Any],
        participants: list[dict[str, Any]],
        run_payload: dict[str, Any],
    ) -> dict[str, Any]:
        task_name = str(task_graph.get("task_name") or task_graph.get("graph_id") or "").strip()
        if not task_name:
            return {"ok": False, "reason": "missing_task_name"}
        status = str(run_payload.get("status") or "").lower()
        if status != "completed":
            return {"ok": False, "reason": "run_not_completed", "status": status}

        parameter_schema = self._collect_parameter_schema(task_graph, participants)
        artifact_paths = self._collect_artifact_paths(task_graph, participants, run_payload)
        execution_mode = "python_artifact" if artifact_paths else "agent_runtime"
        if self._is_llm_generation_profile(participants):
            execution_mode = "llm_generation"

        asset = {
            "asset_id": "asset_" + uuid4().hex[:16],
            "task_name": task_name,
            "task_graph_id": str(task_graph.get("graph_id") or ""),
            "participant_ids": [str(p.get("participant_id") or "") for p in participants if p.get("participant_id")],
            "participant_names": [str(p.get("display_name") or p.get("agent_name") or p.get("name") or "") for p in participants],
            "execution_mode": execution_mode,
            "parameter_schema": parameter_schema,
            "artifact_paths": artifact_paths,
            "last_run_id": str(run_payload.get("run_id") or ""),
            "last_final_answer": self._extract_final_answer(run_payload),
            "created_at": self._now(),
            "updated_at": self._now(),
            "usage_count": 0,
            "active": True,
        }
        with sqlite3.connect(self.sqlite_path) as con:
            con.execute(
                """
                insert into reusable_assets(asset_id, task_name, asset_json, updated_at, active)
                values(?, ?, ?, ?, 1)
                on conflict(task_name) do update set
                    asset_id=excluded.asset_id,
                    asset_json=excluded.asset_json,
                    updated_at=excluded.updated_at,
                    active=1
                """,
                (asset["asset_id"], task_name, json.dumps(asset, ensure_ascii=False), asset["updated_at"]),
            )
        self._append_jsonl("execution_assets.jsonl", asset)
        return {"ok": True, "asset": asset}

    def get_asset(self, task_name: str) -> dict[str, Any] | None:
        name = str(task_name or "").strip()
        if not name:
            return None
        with sqlite3.connect(self.sqlite_path) as con:
            row = con.execute(
                "select asset_json from reusable_assets where task_name=? and active=1 order by updated_at desc limit 1",
                (name,),
            ).fetchone()
        if not row:
            return None
        try:
            data = json.loads(row[0] or "{}")
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def decide(self, task_name: str, provided_inputs: dict[str, Any] | None = None) -> ReuseDecision:
        asset = self.get_asset(task_name)
        if not asset:
            return ReuseDecision(False, "no_reusable_asset")
        missing = self.missing_inputs(asset, provided_inputs or {})
        if missing:
            return ReuseDecision(False, "missing_runtime_inputs", asset=asset, missing_inputs=missing)
        return ReuseDecision(True, "asset_ready", asset=asset, missing_inputs=[])

    def missing_inputs(self, asset: dict[str, Any], provided_inputs: dict[str, Any]) -> list[dict[str, Any]]:
        fields = []
        for item in asset.get("parameter_schema") or []:
            if not isinstance(item, dict):
                continue
            key = str(item.get("field") or item.get("name") or "").strip()
            if not key:
                continue
            required = bool(item.get("required", True))
            if required and provided_inputs.get(key) in (None, "", [], {}):
                fields.append({
                    "field": key,
                    "name": key,
                    "label": item.get("label") or key,
                    "input_type": item.get("input_type") or item.get("type") or "text",
                    "required": True,
                    "description": item.get("description") or "Runtime value required by the reused execution asset.",
                })
        return fields

    async def execute_reused_asset(self, *, asset: dict[str, Any], provided_inputs: dict[str, Any] | None = None) -> dict[str, Any]:
        mode = str(asset.get("execution_mode") or "")
        if mode == "python_artifact":
            paths = [p for p in asset.get("artifact_paths") or [] if isinstance(p, str) and p.strip()]
            existing = [Path(p) for p in paths if Path(p).exists() and Path(p).suffix == ".py"]
            if existing:
                path = existing[0]
                env = {"RUNTIME_INPUTS_JSON": json.dumps(provided_inputs or {}, ensure_ascii=False)}
                result = await RuntimeCommandExecutor().run_exec(
                    [sys.executable, str(path)],
                    cwd=path.parent,
                    env=env,
                    timeout_seconds=int(os.getenv("RUNTIME_REUSE_TIMEOUT_SECONDS", "30")),
                    kind="python",
                )
                self._mark_used(str(asset.get("task_name") or ""))
                return {
                    "ok": result.returncode == 0,
                    "status": "completed" if result.returncode == 0 else "failed",
                    "execution_mode": "python_artifact",
                    "artifact_path": str(path),
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "returncode": result.returncode,
                    "final_answer": (result.stdout or result.stderr or "").strip(),
                    "context_trace": {
                        "task_registry": True,
                        "artifact_registry": True,
                        "planning_used": False,
                        "llm_used": False,
                        "reuse_asset_id": asset.get("asset_id"),
                    },
                }
        if mode == "llm_generation":
            generated = await self._execute_llm_generation(asset=asset, provided_inputs=provided_inputs or {})
            self._mark_used(str(asset.get("task_name") or ""))
            return generated
        return {
            "ok": False,
            "status": "fallback_required",
            "execution_mode": mode or "agent_runtime",
            "reason": "reusable_asset_requires_runtime_execution",
            "context_trace": {
                "task_registry": True,
                "artifact_registry": bool(asset.get("artifact_paths")),
                "planning_used": False,
                "llm_used": mode == "llm_generation",
                "reuse_asset_id": asset.get("asset_id"),
            },
        }

    async def _execute_llm_generation(self, *, asset: dict[str, Any], provided_inputs: dict[str, Any]) -> dict[str, Any]:
        from ai_core.llm.provider_router import ProviderRouter
        prompt_text = (
            "Execute the saved runtime asset directly. Do not re-plan the task.\n"
            "Use the saved task and agent contract plus the runtime inputs to produce the final user-facing result.\n"
            f"Task name: {asset.get('task_name')}\n"
            f"Participants: {json.dumps(asset.get('participant_names') or [], ensure_ascii=False)}\n"
            f"Parameter schema: {json.dumps(asset.get('parameter_schema') or [], ensure_ascii=False)}\n"
            f"Runtime inputs: {json.dumps(provided_inputs or {}, ensure_ascii=False)}\n"
            "Return only the requested final content in final_answer."
        )
        schema = {
            "type": "object",
            "properties": {"final_answer": {"type": "string"}},
            "required": ["final_answer"],
            "additionalProperties": True,
        }
        try:
            result = await ProviderRouter().generate_json(
                run_id="reuse_" + uuid4().hex[:12],
                node_id="execution",
                adapter={"provider_route": [], "max_provider_attempts": 1},
                prompt={"system": "You execute a saved reusable runtime asset.", "user": prompt_text},
                rendered_user_prompt=prompt_text,
                schema=schema,
            )
            answer = str((result or {}).get("final_answer") or "").strip()
            if not answer:
                answer = json.dumps(result, ensure_ascii=False)
            return {
                "ok": True,
                "status": "completed",
                "execution_mode": "llm_generation",
                "final_answer": answer,
                "provider_result": result,
                "context_trace": {
                    "task_registry": True,
                    "agent_registry": True,
                    "artifact_registry": False,
                    "planning_used": False,
                    "llm_used": True,
                    "reuse_asset_id": asset.get("asset_id"),
                },
            }
        except Exception as exc:
            return {
                "ok": False,
                "status": "failed",
                "execution_mode": "llm_generation",
                "final_answer": str(exc),
                "reason": "llm_generation_failed",
                "context_trace": {
                    "task_registry": True,
                    "agent_registry": True,
                    "artifact_registry": False,
                    "planning_used": False,
                    "llm_used": True,
                    "reuse_asset_id": asset.get("asset_id"),
                },
            }

    def save_short_answer(self, *, query: str, answer: str, source: str = "direct") -> None:
        key = self._normalize_query(query)
        if not key or not answer:
            return
        now = self._now()
        record = {"query_key": key, "query": query, "answer": answer, "source": source, "updated_at": now}
        with sqlite3.connect(self.sqlite_path) as con:
            con.execute(
                """
                insert into short_answer_cache(query_key, answer_json, updated_at)
                values(?, ?, ?)
                on conflict(query_key) do update set answer_json=excluded.answer_json, updated_at=excluded.updated_at
                """,
                (key, json.dumps(record, ensure_ascii=False), now),
            )

    def get_short_answer(self, query: str) -> dict[str, Any] | None:
        key = self._normalize_query(query)
        if not key:
            return None
        with sqlite3.connect(self.sqlite_path) as con:
            row = con.execute("select answer_json from short_answer_cache where query_key=?", (key,)).fetchone()
        if not row:
            return None
        try:
            data = json.loads(row[0] or "{}")
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def _init_sqlite(self) -> None:
        with sqlite3.connect(self.sqlite_path) as con:
            con.execute(
                """
                create table if not exists reusable_assets(
                    task_name text primary key,
                    asset_id text not null,
                    asset_json text not null,
                    updated_at text not null,
                    active integer not null default 1
                )
                """
            )
            con.execute(
                """
                create table if not exists short_answer_cache(
                    query_key text primary key,
                    answer_json text not null,
                    updated_at text not null
                )
                """
            )

    def _collect_parameter_schema(self, task_graph: dict[str, Any], participants: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        fields: list[dict[str, Any]] = []
        candidates: list[Any] = []
        candidates.append((task_graph.get("parameter_contract") or {}).get("parameters"))
        candidates.append(task_graph.get("missing_information"))
        for participant in participants:
            contract = participant.get("parameter_contract") if isinstance(participant, dict) else None
            if isinstance(contract, dict):
                candidates.append(contract.get("parameters"))
                candidates.append(contract.get("missing_information"))
        for candidate in candidates:
            if not isinstance(candidate, list):
                continue
            for raw in candidate:
                item = self._normalize_field(raw)
                key = str(item.get("field") or "").strip()
                if key and key not in seen:
                    seen.add(key)
                    fields.append(item)
        return fields

    def _normalize_field(self, raw: Any) -> dict[str, Any]:
        if isinstance(raw, str):
            key = raw.strip()
            return {"field": key, "name": key, "label": key, "input_type": "text", "required": True}
        if isinstance(raw, dict):
            key = str(raw.get("field") or raw.get("name") or raw.get("key") or raw.get("parameter") or "").strip()
            return {
                "field": key,
                "name": key,
                "label": raw.get("label") or key,
                "input_type": raw.get("input_type") or raw.get("type") or "text",
                "required": bool(raw.get("required", True)),
                "description": raw.get("description") or "",
            }
        return {"field": "", "required": False}

    def _collect_artifact_paths(self, *payloads: Any) -> list[str]:
        found: list[str] = []
        def walk(value: Any) -> None:
            if isinstance(value, dict):
                for k, v in value.items():
                    key = str(k).lower()
                    if key in {"path", "file_path", "artifact_path", "script_path", "generated_file", "draft_path"}:
                        self._maybe_add_path(found, v)
                    else:
                        walk(v)
            elif isinstance(value, list):
                for x in value:
                    walk(x)
            elif isinstance(value, str):
                if ".py" in value and ("runtime" in value or value.endswith(".py")):
                    for token in value.replace("\\n", " ").replace("'", " ").replace('"', " ").split():
                        self._maybe_add_path(found, token)
        for payload in payloads:
            walk(payload)
        clean: list[str] = []
        for p in found:
            if p not in clean:
                clean.append(p)
        return clean

    def _maybe_add_path(self, found: list[str], value: Any) -> None:
        if not isinstance(value, str):
            return
        raw = value.strip().strip(",.;:()[]{}<>")
        if not raw.endswith(".py"):
            return
        path = Path(raw)
        if not path.is_absolute():
            path = Path.cwd() / path
        found.append(str(path))

    def _is_llm_generation_profile(self, participants: list[dict[str, Any]]) -> bool:
        for p in participants:
            text = " ".join(str(p.get(k) or "") for k in ("execution_policy", "instruction", "execution_objective", "definition_instruction"))
            lowered = text.casefold()
            if any(marker in lowered for marker in ("llm", "generate", "compose", "write")):
                return True
        return False

    def _extract_final_answer(self, run_payload: dict[str, Any]) -> str:
        synthesis = run_payload.get("synthesis") if isinstance(run_payload, dict) else None
        if isinstance(synthesis, dict):
            return str(synthesis.get("final_answer") or synthesis.get("answer") or "")
        return str(run_payload.get("final_answer") or "") if isinstance(run_payload, dict) else ""

    def _mark_used(self, task_name: str) -> None:
        asset = self.get_asset(task_name)
        if not asset:
            return
        asset["usage_count"] = int(asset.get("usage_count") or 0) + 1
        asset["updated_at"] = self._now()
        with sqlite3.connect(self.sqlite_path) as con:
            con.execute(
                "update reusable_assets set asset_json=?, updated_at=? where task_name=?",
                (json.dumps(asset, ensure_ascii=False), asset["updated_at"], task_name),
            )

    def _append_jsonl(self, filename: str, payload: dict[str, Any]) -> None:
        path = self.root / filename
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _normalize_query(self, query: str) -> str:
        text = str(query or "").strip().casefold()
        text = text.strip(" \t\r\n?.!。？！")
        return " ".join(text.split())

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
