from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import hashlib
import json

from .binding_compiler import BindingCompiler
from .execution_plan_compiler import ExecutionPlanCompiler
from .step_compiler import StepCompiler
from .validation_compiler import TaskGraphCompileGate


@dataclass
class TaskGraphCompiler:
    generated_root: Path = Path("runtime") / "generated" / "tasks"
    step_compiler: StepCompiler = field(default_factory=StepCompiler)
    binding_compiler: BindingCompiler = field(default_factory=BindingCompiler)
    execution_plan_compiler: ExecutionPlanCompiler = field(default_factory=ExecutionPlanCompiler)
    gate: TaskGraphCompileGate = field(default_factory=TaskGraphCompileGate)

    def compile_validate_save(self, task_graph: dict[str, Any]) -> dict[str, Any]:
        compiled = self.compile(task_graph)
        report = self.gate.validate(compiled)
        compiled["validation_report"] = report
        if not report.get("passed"):
            return {"status": "failed", "message": "Task compile failed", "compiled_task": compiled, "validation_report": report}
        path = self.save(compiled)
        return {"status": "completed", "compiled_task": compiled, "compiled_task_path": str(path), "validation_report": report}

    def compile(self, task_graph: dict[str, Any]) -> dict[str, Any]:
        task_id = self._task_id(task_graph)
        steps = self.step_compiler.compile_steps(task_graph)
        bindings = self.binding_compiler.compile(steps, task_graph)
        execution_plan = self.execution_plan_compiler.compile(steps, bindings, task_graph)
        graph = {
            "graph_id": str(task_graph.get("graph_id") or task_id),
            "task_id": task_id,
            "nodes": [self._node_from_step(step) for step in steps],
            "edges": [self._edge_from_binding(binding) for binding in bindings],
        }
        manifest = {
            "task_id": task_id,
            "task_name": str(task_graph.get("task_name") or task_id),
            "compiled_schema_version": "1.0",
            "status": "compiled",
            "source_graph_id": str(task_graph.get("graph_id") or ""),
            "source_instruction_fingerprint": self._fingerprint(str(task_graph.get("instruction") or "")),
            "runtime_prompt_guessing": False,
            "binding_template_parsing_enabled": False,
            "execution_mode": "execute_compiled_task",
        }
        return {
            "task_id": task_id,
            "manifest": manifest,
            "graph": graph,
            "bindings": bindings,
            "execution_plan": execution_plan,
            "steps": steps,
            "source_task_graph": task_graph,
        }

    def save(self, compiled: dict[str, Any]) -> Path:
        task_id = str(compiled.get("task_id") or "compiled_task")
        base = self.generated_root / task_id
        base.mkdir(parents=True, exist_ok=True)
        self._write_json(base / "task_manifest.json", compiled.get("manifest") or {})
        self._write_json(base / "graph.json", compiled.get("graph") or {})
        self._write_json(base / "bindings.json", {"bindings": compiled.get("bindings") or []})
        self._write_json(base / "execution_plan.json", compiled.get("execution_plan") or {})
        self._write_json(base / "validation_report.json", compiled.get("validation_report") or {})
        steps_dir = base / "steps"
        steps_dir.mkdir(exist_ok=True)
        for step in compiled.get("steps") or []:
            if not isinstance(step, dict):
                continue
            step_dir = steps_dir / str(step.get("step_id") or "step")
            step_dir.mkdir(exist_ok=True)
            (step_dir / "instruction.txt").write_text(str(step.get("instruction") or ""), encoding="utf-8")
            for name in ("prompt_profile", "execution_contract", "source_contract", "presentation_contract", "binding_contract"):
                self._write_json(step_dir / f"{name}.json", step.get(name) or {})
        self._write_json(base / "source_task_graph.json", compiled.get("source_task_graph") or {})
        return base

    def _task_id(self, task_graph: dict[str, Any]) -> str:
        name = str(task_graph.get("task_name") or task_graph.get("graph_id") or "compiled_task").strip()
        safe = ''.join(ch if ch.isalnum() or ch in {'_', '-', '.'} else '_' for ch in name).strip('_')
        return safe or "compiled_task"

    def _node_from_step(self, step: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": step.get("step_id"),
            "label": step.get("step_name"),
            "kind": "compiled_step",
            "instruction": step.get("instruction"),
            "prompt_profile": (step.get("prompt_profile") or {}).get("prompt_profile"),
            "execution_contract": step.get("execution_contract") or {},
            "dependencies": step.get("depends_on") or [],
            "bindings": (step.get("binding_contract") or {}).get("bindings") or [],
            "exportable_outputs": (step.get("presentation_contract") or {}).get("exportable_outputs") or [],
        }

    def _edge_from_binding(self, binding: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": binding.get("binding_id"),
            "from": binding.get("source_step"),
            "to": binding.get("target_step"),
            "label": f"{binding.get('source_field')} -> {binding.get('target_field')}",
            "data_contract": "compiled_binding",
        }

    def _write_json(self, path: Path, data: Any) -> None:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    def _fingerprint(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]
