from __future__ import annotations

import ast
import json
import os
import sqlite3
import subprocess
import tempfile
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ai_core.config.paths import RUNTIME_SESSIONS
from ai_core.runtime.environment.runtime_command_executor import RuntimeCommandExecutor
from ai_core.runtime.generated_execution.source_safety import write_bounded_python_copy
from ai_core.context.execution_capability import ExecutionCapabilityResolver


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
        self.capability_resolver = ExecutionCapabilityResolver()
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

        artifact_paths = self._collect_artifact_paths(task_graph, participants, run_payload)
        if artifact_paths:
            # A verified executable artifact is the strongest reusable asset.
            # Do not downgrade it to model generation just because the original
            # agent instruction used words such as "write" or "generate".
            execution_mode = "python_artifact"
            parameter_schema = self._collect_artifact_parameter_schema(artifact_paths)
        else:
            parameter_schema = self._collect_parameter_schema(task_graph, participants)
            execution_mode = "llm_generation" if self._is_llm_generation_profile(participants) else "agent_runtime"

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
        provided = provided_inputs or {}
        # When a reusable asset has not yet received a usable value for any of
        # its required contract fields, expose the full saved input contract once,
        # including optional fields.  Do not use len(provided)==0 here: generic
        # runtime state can contain unrelated keys, placeholders, or metadata,
        # and those must not hide optional fields from the first user-facing
        # collection screen.  After at least one required field has a usable
        # value, only missing required fields can block execution.
        include_optional = not self._has_usable_required_contract_value(asset, provided)
        missing = self.missing_inputs(asset, provided, include_optional=include_optional)
        if missing:
            return ReuseDecision(False, "missing_runtime_inputs", asset=asset, missing_inputs=missing)
        return ReuseDecision(True, "asset_ready", asset=asset, missing_inputs=[])


    def _has_usable_required_contract_value(self, asset: dict[str, Any], provided_inputs: dict[str, Any]) -> bool:
        provided = provided_inputs or {}
        if not isinstance(provided, dict):
            return False
        for item in asset.get("parameter_schema") or []:
            if not isinstance(item, dict):
                continue
            if not bool(item.get("required", True)):
                continue
            key = str(item.get("field") or item.get("name") or "").strip()
            if not key:
                continue
            value = provided.get(key)
            if value not in (None, "", [], {}):
                return True
        return False

    def missing_inputs(self, asset: dict[str, Any], provided_inputs: dict[str, Any], *, include_optional: bool = False) -> list[dict[str, Any]]:
        fields = []
        provided = provided_inputs or {}
        for item in asset.get("parameter_schema") or []:
            if not isinstance(item, dict):
                continue
            key = str(item.get("field") or item.get("name") or "").strip()
            if not key:
                continue
            required = bool(item.get("required", True))
            value_missing = provided.get(key) in (None, "", [], {})
            if value_missing and (required or include_optional):
                fields.append({
                    "field": key,
                    "name": key,
                    "label": item.get("label") or key,
                    "input_type": item.get("input_type") or item.get("type") or "text",
                    "required": required,
                    "description": item.get("description") or ("Runtime value required by the reusable executable asset." if required else "Optional value accepted by the reusable executable asset."),
                })
        return fields

    async def execute_reused_asset(self, *, asset: dict[str, Any], provided_inputs: dict[str, Any] | None = None) -> dict[str, Any]:
        capability = self.capability_resolver.resolve(asset, provided_inputs or {})
        if capability.mode == "executable_artifact" and capability.artifact_paths:
            path = Path(capability.artifact_paths[0])
            result = await self._execute_python_artifact(
                path=path,
                asset=asset,
                provided_inputs=provided_inputs or {},
                function_name=capability.callable_name,
                capability_reason=capability.reason,
            )
            self._mark_used(str(asset.get("task_name") or ""))
            return result

        if capability.mode == "model_generation":
            generated = await self._execute_llm_generation(asset=asset, provided_inputs=provided_inputs or {})
            self._mark_used(str(asset.get("task_name") or ""))
            return generated
        return {
            "ok": False,
            "status": "fallback_required",
            "execution_mode": capability.mode,
            "reason": capability.reason,
            "capability": capability.__dict__,
            "context_trace": {
                "task_registry": True,
                "agent_registry": True,
                "artifact_registry": bool(capability.artifact_paths),
                "planning_used": capability.requires_planning,
                "llm_used": capability.requires_model,
                "reuse_asset_id": asset.get("asset_id"),
                "capability_mode": capability.mode,
                "capability_reason": capability.reason,
            },
        }

    async def _execute_python_artifact(self, *, path: Path, asset: dict[str, Any], provided_inputs: dict[str, Any], function_name: str | None = None, capability_reason: str = "") -> dict[str, Any]:
        env = {"RUNTIME_INPUTS_JSON": json.dumps(provided_inputs or {}, ensure_ascii=False)}
        function_name = function_name or self._select_artifact_function(path, provided_inputs)
        if function_name:
            runner = self._build_function_runner(path=path, function_name=function_name, provided_inputs=provided_inputs)
            command = [sys.executable, "-u", "-c", runner]
            cwd = path.parent
        else:
            executable_path = write_bounded_python_copy(path)
            command = [sys.executable, "-u", str(executable_path)]
            cwd = executable_path.parent
        result = await self._run_python_artifact_bounded(command=command, cwd=cwd, env=env)
        stdout = self._normalize_process_output(result.get("stdout") or "")
        stderr = self._normalize_process_output(result.get("stderr") or "")
        has_useful_output = bool(stdout.strip())
        completed = result.get("returncode") == 0 or (result.get("timed_out") and has_useful_output)
        final_answer = (stdout or stderr or result.get("reason") or "").strip()
        return {
            "ok": completed,
            "status": "completed" if completed else "failed",
            "execution_mode": "python_artifact",
            "artifact_path": str(path),
            "invoked_function": function_name,
            "stdout": stdout,
            "stderr": stderr,
            "returncode": result.get("returncode"),
            "timed_out": bool(result.get("timed_out")),
            "bounded_by_runtime": bool(result.get("bounded_by_runtime")),
            "final_answer": final_answer,
            "context_trace": {
                "task_registry": True,
                "agent_registry": True,
                "artifact_registry": True,
                "planning_used": False,
                "llm_used": False,
                "reuse_asset_id": asset.get("asset_id"),
                "capability_mode": "executable_artifact",
                "capability_reason": capability_reason or "verified_executable_artifact",
            },
        }

    async def _run_python_artifact_bounded(self, *, command: list[str], cwd: Path, env: dict[str, str]) -> dict[str, Any]:
        import asyncio
        timeout = max(2, int(os.getenv("RUNTIME_REUSE_TIMEOUT_SECONDS", "30")))
        proc_env = os.environ.copy()
        proc_env.update({str(k): str(v) for k, v in (env or {}).items()})

        def _run() -> dict[str, Any]:
            try:
                completed = subprocess.run(
                    command,
                    cwd=str(cwd),
                    env=proc_env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout,
                )
                return {
                    "returncode": completed.returncode,
                    "stdout": completed.stdout or "",
                    "stderr": completed.stderr or "",
                    "timed_out": False,
                    "bounded_by_runtime": False,
                    "reason": "",
                }
            except subprocess.TimeoutExpired as exc:
                return {
                    "returncode": 124,
                    "stdout": self._decode_timeout_stream(getattr(exc, "stdout", "")),
                    "stderr": self._decode_timeout_stream(getattr(exc, "stderr", "")),
                    "timed_out": True,
                    "bounded_by_runtime": True,
                    "reason": "process_exceeded_runtime_window",
                }
            except FileNotFoundError as exc:
                return {"returncode": 127, "stdout": "", "stderr": str(exc), "timed_out": False, "bounded_by_runtime": False, "reason": "command_not_found"}
            except Exception as exc:
                return {"returncode": 1, "stdout": "", "stderr": str(exc), "timed_out": False, "bounded_by_runtime": False, "reason": "command_error"}

        return await asyncio.to_thread(_run)

    def _decode_timeout_stream(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    def _normalize_process_output(self, text: str, *, max_lines: int = 12, max_chars: int = 2000) -> str:
        raw = str(text or "")
        if not raw.strip():
            return ""
        raw = self._compact_repeated_segments(raw)
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if not lines:
            lines = [raw.strip()]
        compact: list[str] = []
        suppressed = 0
        previous_raw = None
        for line in lines:
            line = self._compact_repeated_segments(line)
            if line == previous_raw:
                suppressed += 1
                continue
            previous_raw = line
            if compact and self._lines_are_redundant(compact[-1], line):
                # Keep the more informative representative of a near-duplicate
                # output group. This is evidence-structure based: it compares
                # line similarity after removing volatile numbers/punctuation and
                # does not depend on task names or business vocabulary.
                compact[-1] = line if len(line) >= len(compact[-1]) else compact[-1]
                suppressed += 1
                continue
            compact.append(line)
            if len(compact) >= max_lines:
                break
        result = "\n".join(compact)
        if suppressed:
            result += f"\n...[{suppressed} repeated or redundant output lines compacted]"
        if len(result) > max_chars:
            result = result[:max_chars].rstrip() + " ...[truncated]"
        return result

    def _compact_repeated_segments(self, text: str) -> str:
        import re
        value = str(text or "").strip()
        if not value:
            return ""
        # Collapse exact adjacent repeated fragments even when a generated tool
        # prints them on a single line instead of separate stdout lines.  The
        # detection is structural and language-agnostic: it looks for adjacent
        # repeated spans and keeps one representative.
        for _ in range(4):
            new_value = re.sub(r"(?s)\b(.{8,240}?)\s+\1\b", r"\1", value)
            if new_value == value:
                break
            value = new_value.strip()
        return value

    def _lines_are_redundant(self, a: str, b: str) -> bool:
        left = self._line_signature(a)
        right = self._line_signature(b)
        if not left or not right:
            return False
        if left == right:
            return True
        sa, sb = set(left.split()), set(right.split())
        if not sa or not sb:
            return False
        overlap = len(sa & sb) / max(1, min(len(sa), len(sb)))
        prefix_related = left in right or right in left
        return overlap >= 0.65 or prefix_related

    def _line_signature(self, text: str) -> str:
        import re
        lowered = str(text or "").casefold()
        lowered = re.sub(r"\d+(?:[:./-]\d+)*", " ", lowered)
        lowered = re.sub(r"[^a-z_]+", " ", lowered)
        return " ".join(part for part in lowered.split() if len(part) > 1)

    def _select_artifact_function(self, path: Path, provided_inputs: dict[str, Any]) -> str | None:
        functions = self._public_python_functions(path)
        if not functions:
            return None
        input_keys = {str(k) for k in (provided_inputs or {}).keys()}
        for fn in functions:
            args = set(fn.get("args") or [])
            if args and args.issubset(input_keys):
                return str(fn.get("name") or "")
        if len(functions) == 1 and (functions[0].get("args") or []):
            return str(functions[0].get("name") or "")
        return None

    def _build_function_runner(self, *, path: Path, function_name: str, provided_inputs: dict[str, Any]) -> str:
        return "\n".join([
            "import importlib.util, json",
            f"module_path = {json.dumps(str(path))}",
            "inputs = json.loads(" + json.dumps(json.dumps(provided_inputs or {}, ensure_ascii=False)) + ")",
            "spec = importlib.util.spec_from_file_location('runtime_reuse_module', module_path)",
            "module = importlib.util.module_from_spec(spec)",
            "spec.loader.exec_module(module)",
            f"fn = getattr(module, {json.dumps(function_name)})",
            "import inspect",
            "sig = inspect.signature(fn)",
            "kwargs = {name: inputs[name] for name in sig.parameters.keys() if name in inputs}",
            "result = fn(**kwargs)",
            "print(json.dumps(result, ensure_ascii=False, default=str) if not isinstance(result, str) else result)",
        ])

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
            con.execute(
                """
                create table if not exists repair_candidates(
                    repair_id text primary key,
                    task_name text not null,
                    asset_id text not null,
                    repair_json text not null,
                    status text not null,
                    created_at text not null
                )
                """
            )

    def _collect_artifact_parameter_schema(self, artifact_paths: list[str]) -> list[dict[str, Any]]:
        fields: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in artifact_paths:
            path = Path(raw)
            if not path.exists() or path.suffix != ".py":
                continue
            for fn in self._public_python_functions(path):
                for arg in fn.get("args") or []:
                    key = str(arg).strip()
                    if key and key not in seen:
                        seen.add(key)
                        fields.append({
                            "field": key,
                            "name": key,
                            "label": key,
                            "input_type": self._annotation_to_input_type((fn.get("annotations") or {}).get(key)),
                            "required": key not in set(fn.get("defaults") or []),
                            "description": "Runtime value required by the reusable executable artifact.",
                        })
                if fields:
                    return fields
        return fields

    def _public_python_functions(self, path: Path) -> list[dict[str, Any]]:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        functions: list[dict[str, Any]] = []
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef) or node.name.startswith("_"):
                continue
            args = [a.arg for a in node.args.args if a.arg not in {"self", "cls"}]
            defaults = args[len(args) - len(node.args.defaults):] if node.args.defaults else []
            annotations: dict[str, str] = {}
            for a in node.args.args:
                if a.annotation is not None:
                    annotations[a.arg] = ast.unparse(a.annotation) if hasattr(ast, "unparse") else ""
            functions.append({"name": node.name, "args": args, "defaults": defaults, "annotations": annotations})
        return functions

    def _annotation_to_input_type(self, annotation: Any) -> str:
        text = str(annotation or "").casefold()
        if "list" in text or text.startswith("sequence") or text.startswith("tuple"):
            return "list"
        if "int" in text:
            return "number"
        if "float" in text or "decimal" in text:
            return "number"
        if "bool" in text:
            return "checkbox"
        return "text"

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
            return self.compact_final_answer(str(synthesis.get("final_answer") or synthesis.get("answer") or ""))
        return self.compact_final_answer(str(run_payload.get("final_answer") or "")) if isinstance(run_payload, dict) else ""

    def compact_final_answer(self, text: str) -> str:
        raw = str(text or "").strip()
        if raw.startswith("{"):
            try:
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    for key in ("final_answer", "answer", "result", "message", "text"):
                        value = payload.get(key)
                        if isinstance(value, str) and value.strip():
                            raw = value.strip()
                            break
            except Exception:
                pass
        return self._normalize_process_output(raw, max_lines=40, max_chars=8000)

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

    def record_repair_candidate(self, *, task_name: str | None, feedback: str, run_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Record user feedback as a generic self-repair candidate.

        The runtime does not patch source code blindly. It stores the failing
        asset/run evidence and the user's feedback so the next execution can
        prefer verifiable repair paths or a human-approved regeneration flow.
        """
        target = str(task_name or "").strip()
        asset = self.get_asset(target) if target else None
        now = self._now()
        record = {
            "repair_id": "repair_" + uuid4().hex[:16],
            "task_name": target,
            "asset_id": (asset or {}).get("asset_id"),
            "feedback": str(feedback or ""),
            "run_id": str((run_payload or {}).get("run_id") or ""),
            "status": "candidate",
            "created_at": now,
        }
        with sqlite3.connect(self.sqlite_path) as con:
            con.execute(
                """
                insert into repair_candidates(repair_id, task_name, asset_id, repair_json, status, created_at)
                values(?, ?, ?, ?, ?, ?)
                """,
                (record["repair_id"], target, record.get("asset_id") or "", json.dumps(record, ensure_ascii=False), record["status"], now),
            )
        self._append_jsonl("repair_candidates.jsonl", record)
        return record

    def latest_repair_candidate(self, task_name: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.sqlite_path) as con:
            row = con.execute(
                "select repair_json from repair_candidates where task_name=? order by created_at desc limit 1",
                (str(task_name or "").strip(),),
            ).fetchone()
        if not row:
            return None
        try:
            data = json.loads(row[0] or "{}")
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
