from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json

from .project_paths import generated_tasks_dir


@dataclass(frozen=True)
class CompiledTaskLoader:
    generated_root: Path = field(default_factory=generated_tasks_dir)

    def load(self, task_id: str) -> dict[str, Any] | None:
        base = self.generated_root / self._safe(task_id)
        if not base.exists() or not base.is_dir():
            return None
        manifest = self._read_json(base / "task_manifest.json")
        graph = self._read_json(base / "graph.json")
        bindings = self._read_json(base / "bindings.json")
        execution_plan = self._read_json(base / "execution_plan.json")
        validation_report = self._read_json(base / "validation_report.json")
        source_task_graph = self._read_json(base / "source_task_graph.json")
        steps: list[dict[str, Any]] = []
        steps_dir = base / "steps"
        if steps_dir.exists():
            for step_dir in sorted(p for p in steps_dir.iterdir() if p.is_dir()):
                steps.append({
                    "step_id": step_dir.name,
                    "instruction": (step_dir / "instruction.txt").read_text(encoding="utf-8") if (step_dir / "instruction.txt").exists() else "",
                    "prompt_profile": self._read_json(step_dir / "prompt_profile.json"),
                    "execution_contract": self._read_json(step_dir / "execution_contract.json"),
                    "source_contract": self._read_json(step_dir / "source_contract.json"),
                    "presentation_contract": self._read_json(step_dir / "presentation_contract.json"),
                    "binding_contract": self._read_json(step_dir / "binding_contract.json"),
                    "execution_known": self._read_json(step_dir / "execution_known.json"),
                    "semantic_known": self._read_json(step_dir / "semantic_known.json"),
                    "task_metadata": self._read_json(step_dir / "task_metadata.json"),
                })
        return {
            "task_id": self._safe(task_id),
            "base_path": str(base),
            "manifest": manifest,
            "graph": graph,
            "bindings": bindings.get("bindings") if isinstance(bindings, dict) else [],
            "execution_plan": execution_plan,
            "validation_report": validation_report,
            "source_task_graph": source_task_graph,
            "steps": steps,
        }

    def as_task_graph(self, task_id: str) -> dict[str, Any] | None:
        compiled = self.load(task_id)
        if not compiled:
            return None
        report = compiled.get("validation_report") if isinstance(compiled.get("validation_report"), dict) else {}
        if report.get("passed") is not True:
            return None
        graph = compiled.get("source_task_graph") if isinstance(compiled.get("source_task_graph"), dict) else {}
        graph = dict(graph)
        graph["tasks"] = self._merge_compiled_contracts(graph.get("tasks"), compiled.get("steps"))
        graph["compiled_task"] = {
            "task_id": compiled.get("task_id"),
            "base_path": compiled.get("base_path"),
            "manifest": compiled.get("manifest"),
            "execution_plan": compiled.get("execution_plan"),
            "bindings": compiled.get("bindings") or [],
            "contracts_applied_to_tasks": True,
        }
        return graph

    def _merge_compiled_contracts(self, tasks: Any, compiled_steps: Any) -> list[dict[str, Any]]:
        raw_tasks = tasks if isinstance(tasks, list) else []
        steps = compiled_steps if isinstance(compiled_steps, list) else []
        by_key: dict[str, dict[str, Any]] = {}
        for step in steps:
            if not isinstance(step, dict):
                continue
            for value in (step.get("step_id"), step.get("participant_id")):
                key = str(value or "").strip()
                if key:
                    by_key[key] = step
        merged: list[dict[str, Any]] = []
        for raw in raw_tasks:
            if not isinstance(raw, dict):
                continue
            keys = [raw.get("source_step_id"), raw.get("step_id"), raw.get("participant_id"), raw.get("id")]
            compiled = next((by_key.get(str(k or "").strip()) for k in keys if str(k or "").strip() in by_key), None)
            if not compiled:
                merged.append(dict(raw))
                continue
            item = dict(raw)
            for name in ("prompt_profile", "execution_contract", "source_contract", "presentation_contract", "binding_contract", "context_contract", "execution_known", "semantic_known", "task_metadata"):
                value = compiled.get(name)
                if isinstance(value, dict):
                    item[name] = value
            item["compiled_step_id"] = compiled.get("step_id")
            item["compiled_step_contract_applied"] = True
            merged.append(item)
        return merged

    def _read_json(self, path: Path) -> dict[str, Any]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _safe(self, value: str) -> str:
        text = str(value or "").strip()
        safe = ''.join(ch if ch.isalnum() or ch in {'_', '-', '.'} else '_' for ch in text).strip('_')
        return safe or "compiled_task"
