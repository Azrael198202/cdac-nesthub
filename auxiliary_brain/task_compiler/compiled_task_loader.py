from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json

from .project_paths import generated_tasks_dir
from auxiliary_brain.runtime.execution.reuse_policy import ExecutionReusePolicyClassifier


@dataclass(frozen=True)
class CompiledTaskLoader:
    generated_root: Path = field(default_factory=generated_tasks_dir)
    reuse_policy_classifier: ExecutionReusePolicyClassifier = field(default_factory=ExecutionReusePolicyClassifier)

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
                    "execution_reuse_policy": self._read_json(step_dir / "execution_reuse_policy.json"),
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

        source_graph = compiled.get("source_task_graph") if isinstance(compiled.get("source_task_graph"), dict) else {}
        graph = dict(source_graph)

        # Execute from the compiled artifact, not from the creation-time source
        # graph.  The source graph may contain durable-agent ids and generated
        # step ids from before compilation.  The compiled graph is the authority
        # for step ids, dependencies, and binding edges.
        compiled_tasks = self._tasks_from_compiled_graph(compiled)
        graph["tasks"] = compiled_tasks or self._merge_compiled_contracts(graph.get("tasks"), compiled.get("steps"))
        graph["selected_participant_ids"] = self._payload_participant_ids(graph.get("tasks"))

        bindings = compiled.get("bindings") if isinstance(compiled.get("bindings"), list) else []
        graph["workflow_variable_contract"] = {
            "contract_type": "compiled_workflow_variable_contract",
            "bindings": bindings,
            "execution_reuse_policy": ((compiled.get("manifest") or {}).get("execution_reuse_policy") if isinstance(compiled.get("manifest"), dict) else {}) or graph.get("execution_reuse_policy"),
            "template_parsing_enabled": False,
        }
        graph = self.reuse_policy_classifier.apply_to_task_graph(graph)
        graph["compiled_task"] = {
            "task_id": compiled.get("task_id"),
            "base_path": compiled.get("base_path"),
            "manifest": compiled.get("manifest"),
            "execution_plan": compiled.get("execution_plan"),
            "bindings": bindings,
            "execution_reuse_policy": ((compiled.get("manifest") or {}).get("execution_reuse_policy") if isinstance(compiled.get("manifest"), dict) else {}) or graph.get("execution_reuse_policy"),
            "contracts_applied_to_tasks": True,
            "selected_participant_ids_rebuilt_from_compiled_steps": True,
            "compiled_graph_is_execution_authority": True,
        }
        return graph

    def _tasks_from_compiled_graph(self, compiled: dict[str, Any]) -> list[dict[str, Any]]:
        graph = compiled.get("graph") if isinstance(compiled.get("graph"), dict) else {}
        nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
        steps = compiled.get("steps") if isinstance(compiled.get("steps"), list) else []
        execution_plan = compiled.get("execution_plan") if isinstance(compiled.get("execution_plan"), dict) else {}
        plan_steps = execution_plan.get("steps") if isinstance(execution_plan.get("steps"), list) else []
        source_graph = compiled.get("source_task_graph") if isinstance(compiled.get("source_task_graph"), dict) else {}
        source_tasks = source_graph.get("tasks") if isinstance(source_graph.get("tasks"), list) else []
        by_step = {str(x.get("step_id") or "").strip(): x for x in steps if isinstance(x, dict)}
        plan_by_step = {str(x.get("step_id") or "").strip(): x for x in plan_steps if isinstance(x, dict)}

        def original_for_index(index: int) -> dict[str, Any]:
            if 0 <= index < len(source_tasks) and isinstance(source_tasks[index], dict):
                return source_tasks[index]
            return {}

        out: list[dict[str, Any]] = []
        for index, node in enumerate(nodes, start=1):
            if not isinstance(node, dict):
                continue
            sid = str(node.get("id") or node.get("step_id") or f"step_{index:03d}").strip()
            if not sid:
                continue
            step = by_step.get(sid) or {}
            plan = plan_by_step.get(sid) or {}
            original = original_for_index(index - 1)
            execution_contract = node.get("execution_contract") if isinstance(node.get("execution_contract"), dict) else step.get("execution_contract") if isinstance(step.get("execution_contract"), dict) else {}
            capability_id = str(execution_contract.get("capability_id") or "").strip()
            profile = original.get("capability_profile") if isinstance(original.get("capability_profile"), dict) else {}
            if capability_id and not profile:
                profile = {
                    "capability_type": "runtime_registered_tool",
                    "tool_id": capability_id,
                    "capability": capability_id,
                }
            depends_on = node.get("dependencies") if isinstance(node.get("dependencies"), list) else plan.get("depends_on") if isinstance(plan.get("depends_on"), list) else []
            binding_contract = step.get("binding_contract") if isinstance(step.get("binding_contract"), dict) else {}
            node_bindings = node.get("bindings") if isinstance(node.get("bindings"), list) else []
            if node_bindings:
                binding_contract = {**binding_contract, "bindings": node_bindings, "template_parsing_enabled": False}
            name = str(node.get("label") or original.get("participant_display_name") or original.get("display_name") or original.get("name") or sid).strip()
            instruction = str(node.get("instruction") or step.get("instruction") or original.get("source_instruction_fragment") or original.get("execution_objective") or original.get("instruction") or "").strip()
            original_participant_id = str(original.get("participant_id") or original.get("id") or "").strip()
            out.append({
                **original,
                "id": sid,
                "step_id": sid,
                "compiled_step_id": sid,
                "source_step_id": sid,
                "original_participant_id": original_participant_id,
                "durable_participant_id": original_participant_id,
                "declared_participant_id": original_participant_id,
                "participant_id": sid,
                "participant_display_name": name,
                "display_name": name,
                "name": name,
                "agent_name": name,
                "source_instruction_fragment": instruction,
                "execution_objective": instruction,
                "instruction": instruction,
                "depends_on": [str(x).strip() for x in depends_on if str(x).strip()],
                "input_from": [str(x).strip() for x in depends_on if str(x).strip()],
                "input_contract": {
                    "contract_type": "runtime_step_input_contract",
                    "bound_from_upstream": [str(x).strip() for x in depends_on if str(x).strip()],
                    "accepts_verified_material": bool(depends_on),
                    "user_input_required_for_bound_material": False,
                },
                "output_contract": {
                    "contract_type": "runtime_step_output_contract",
                    "produces_verified_material": True,
                    "planner_metadata_is_not_result_material": True,
                },
                "prompt_profile": step.get("prompt_profile") if isinstance(step.get("prompt_profile"), dict) else {},
                "execution_contract": execution_contract,
                "source_contract": step.get("source_contract") if isinstance(step.get("source_contract"), dict) else {},
                "presentation_contract": step.get("presentation_contract") if isinstance(step.get("presentation_contract"), dict) else {},
                "binding_contract": binding_contract,
                "execution_known": step.get("execution_known") if isinstance(step.get("execution_known"), dict) else {},
                "semantic_known": step.get("semantic_known") if isinstance(step.get("semantic_known"), dict) else {},
                "task_metadata": step.get("task_metadata") if isinstance(step.get("task_metadata"), dict) else {},
                "execution_reuse_policy": step.get("execution_reuse_policy") if isinstance(step.get("execution_reuse_policy"), dict) else {},
                "capability_profile": profile,
                "execution_policy": "runtime_registered_tool" if capability_id else str(original.get("execution_policy") or "delegate_to_ai_core"),
                "workflow_step_type": "runtime_capability" if capability_id else str(original.get("workflow_step_type") or original.get("step_type") or "semantic_intermediate_step"),
                "compiled_graph_node": True,
            })
        return out


    def _payload_participant_ids(self, tasks: Any) -> list[str]:
        ids: list[str] = []
        seen: set[str] = set()
        for task in tasks if isinstance(tasks, list) else []:
            if not isinstance(task, dict):
                continue
            # Task-level controllers are scheduling policy, not executable
            # payload steps.  This is contract-driven and does not depend on
            # any business domain.
            step_type = str(task.get("step_type") or task.get("workflow_step_type") or "").strip().casefold()
            if step_type in {"schedule_controller", "scheduled_trigger", "task_controller"}:
                continue
            pid = str(task.get("participant_id") or task.get("participant") or task.get("agent_id") or "").strip()
            if pid and pid not in seen:
                seen.add(pid)
                ids.append(pid)
        return ids

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
            for name in ("prompt_profile", "execution_contract", "source_contract", "presentation_contract", "binding_contract", "context_contract", "execution_known", "semantic_known", "task_metadata", "execution_reuse_policy"):
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
