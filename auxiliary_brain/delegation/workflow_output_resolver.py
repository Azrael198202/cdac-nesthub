from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import re


@dataclass(frozen=True)
class TemplateResolution:
    value: Any
    unresolved: list[dict[str, Any]]
    changed: bool = False


class WorkflowOutputResolver:
    """Resolve workflow step output references for downstream steps.

    This resolver is intentionally domain-neutral.  It knows nothing about any
    tool or business operation.  It only enforces the workflow dataflow
    contract: ``{{step.field}}`` may read public/exportable material from an
    already completed upstream step, and unresolved/internal placeholders must
    never be passed to downstream side-effecting nodes.
    """

    _TEMPLATE_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
    _PUBLIC_FIELD_NAMES = (
        "final_answer",
        "answer",
        "answer_material",
        "final_content",
        "content",
        "text",
        "output",
        "material",
        "result",
        "message",
        "data",
    )
    _PLACEHOLDER_MARKERS = (
        "completed without a user-facing final answer",
        "intermediate node data was intentionally not exposed",
        "no user-facing final answer",
        "workflow initialized",
        "initializing workflow",
        "the workflow is blocked",
        "please review the blocked step details",
    )

    def normalize_key(self, value: Any) -> str:
        text = str(value or "").strip().casefold()
        text = re.sub(r"\s+", "", text)
        text = text.replace("-", "_")
        text = re.sub(r"_+", "_", text)
        return text.strip("_")

    def is_public_material(self, value: Any) -> bool:
        if value in (None, "", [], {}):
            return False
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return False
            lowered = text.casefold()
            if lowered in {"initializing", "pending", "planning", "planning_active", "ready_for_planning", "completed", "failed", "success"}:
                return False
            if "{{" in text or "}}" in text:
                return False
            if any(marker in lowered for marker in self._PLACEHOLDER_MARKERS):
                return False
            internal_labels = {
                "input_parsing", "intent_recognition", "requirement_completion",
                "context_awareness", "workflow_planning", "agent_action_planning",
                "execution_preparation", "pre_execution_validation", "execution",
                "result_verification", "feedback_repair", "final_synthesis",
                "dataflow_step", "runtime_error", "tool_execution",
            }
            normalized_label = re.sub(r"[^a-z0-9_]+", "_", lowered).strip("_")
            if normalized_label in internal_labels:
                return False
            return True
        return True

    def first_scalar(self, value: Any) -> str:
        if value in (None, "", [], {}):
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (int, float, bool)):
            return str(value)
        if isinstance(value, list):
            parts = [self.first_scalar(item) for item in value]
            return "\n".join([p for p in parts if p]).strip()
        if isinstance(value, dict):
            for key in self._PUBLIC_FIELD_NAMES:
                if key in value:
                    text = self.first_scalar(value.get(key))
                    if text:
                        return text
            return "\n".join([self.first_scalar(v) for v in value.values() if self.first_scalar(v)]).strip()
        return str(value)

    def extract_public_fields(self, result: Any) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        direct_answer = getattr(result, "final_answer", None)
        if self.is_public_material(direct_answer):
            fields["final_answer"] = str(direct_answer).strip() if isinstance(direct_answer, str) else direct_answer
        workflow_results = getattr(result, "workflow_results", None)
        if isinstance(workflow_results, dict):
            self._collect_public_fields(workflow_results, fields)
        primary = self.first_scalar(fields.get("final_answer") or fields.get("answer") or fields.get("result") or fields.get("content") or fields.get("text"))
        if primary and self.is_public_material(primary):
            fields.setdefault("final_answer", primary)
            fields.setdefault("answer", primary)
            fields.setdefault("text", primary)
            fields.setdefault("result", primary)
        return {k: v for k, v in fields.items() if self.is_public_material(v)}

    def _collect_public_fields(self, node: Any, out: dict[str, Any], prefix: str = "") -> None:
        """Collect only terminal/public output fields.

        This traversal is deliberately conservative.  It may walk through the
        result tree to find terminal containers, but it only exports values from
        nodes that are explicitly public/exportable or whose path is a terminal
        output path.  Internal pipeline stages, lifecycle labels, planning nodes,
        and generic status strings never become workflow variables.
        """
        if isinstance(node, dict):
            status = str(node.get("status") or node.get("execution_status") or node.get("_status") or "").strip().casefold()
            if status in {"initializing", "pending", "planning", "planning_active", "ready_for_planning", "blocked", "failed", "error"}:
                # A failed/non-terminal container can still have nested terminal
                # child objects in some persistence formats, so do not return
                # before walking children.  Only this exact node is ineligible.
                node_exportable = False
            else:
                node_exportable = True
            if node.get("blocked_steps") or node.get("missing_inputs") or node.get("pending_action"):
                node_exportable = False
            explicit_public = bool(node.get("exportable") or node.get("user_facing") or node.get("public") or node.get("public_output"))
            terminal_path = self._is_terminal_public_path(prefix)
            can_export_here = node_exportable and (explicit_public or terminal_path)
            for key, value in node.items():
                key_text = str(key)
                path = f"{prefix}.{key_text}" if prefix else key_text
                if can_export_here and key_text in self._PUBLIC_FIELD_NAMES and self.is_public_material(value):
                    out.setdefault(key_text, value)
                    out.setdefault(path, value)
                if isinstance(value, (dict, list)):
                    self._collect_public_fields(value, out, path)
        elif isinstance(node, list):
            for index, item in enumerate(node[:50]):
                child_path = f"{prefix}[{index}]" if prefix else f"[{index}]"
                self._collect_public_fields(item, out, child_path)
        elif isinstance(node, str) and prefix and self.is_public_material(node):
            tail = prefix.rsplit(".", 1)[-1]
            if tail in self._PUBLIC_FIELD_NAMES and self._is_terminal_public_path(prefix):
                out.setdefault(tail, node)
                out.setdefault(prefix, node)

    def _is_terminal_public_path(self, path: str) -> bool:
        lowered = str(path or "").casefold()
        # Match path segments, not arbitrary substrings, so an internal key that
        # happens to contain a word such as "output_schema" is not exportable.
        segments = [seg for seg in re.split(r"[.\[\]/]+", lowered) if seg]
        terminal_markers = {"final_synthesis", "conversation_output", "output", "synthesis", "final", "dataflow_step", "delivery"}
        return any(seg in terminal_markers for seg in segments)

    def build_reference_map(
        self,
        *,
        completed_results: list[Any],
        dependency_ids: set[str] | None = None,
        task_graph: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        refs: dict[str, Any] = {}
        included_index = 0
        dependency_ids = {str(x).strip() for x in (dependency_ids or set()) if str(x).strip()}
        for absolute_index, result in enumerate(completed_results or [], start=1):
            result_pid = str(getattr(result, "participant_id", "") or "").strip()
            result_name = str(getattr(result, "participant_name", "") or "").strip()
            if dependency_ids and result_pid not in dependency_ids and result_name not in dependency_ids:
                continue
            status = str(getattr(result, "status", "") or "").strip().casefold()
            if status not in {"completed", "success", "succeeded", "ok"}:
                continue
            fields = self.extract_public_fields(result)
            if not fields:
                continue
            included_index += 1
            aliases = self.aliases_for_result(
                absolute_index=absolute_index,
                included_index=included_index,
                result_pid=result_pid,
                result_name=result_name,
                task_graph=task_graph,
            )
            primary = fields.get("final_answer") or fields.get("answer") or fields.get("result") or fields.get("text")
            for alias in aliases:
                norm_alias = self.normalize_key(alias)
                if not norm_alias:
                    continue
                if self.is_public_material(primary):
                    refs[norm_alias] = primary
                for field_name, field_value in fields.items():
                    if self.is_public_material(field_value):
                        refs[self.normalize_key(f"{alias}.{field_name}")] = field_value
        return refs

    def aliases_for_result(self, *, absolute_index: int, included_index: int, result_pid: str, result_name: str, task_graph: dict[str, Any] | None) -> list[str]:
        aliases = [
            f"step{absolute_index}", f"step_{absolute_index}", f"step {absolute_index}",
            f"stage{absolute_index}", f"stage_{absolute_index}", f"stage {absolute_index}",
            f"result{absolute_index}", f"result_{absolute_index}", f"result {absolute_index}",
        ]
        if included_index != absolute_index:
            aliases.extend([f"step{included_index}", f"step_{included_index}", f"step {included_index}"])
        if result_pid:
            aliases.append(result_pid)
        if result_name:
            aliases.extend([result_name, re.sub(r"[^A-Za-z0-9_]+", "_", result_name).strip("_")])
        aliases.extend(self._task_graph_aliases(result_pid=result_pid, result_name=result_name, task_graph=task_graph))
        # Preserve order while deduplicating.
        seen: set[str] = set()
        out: list[str] = []
        for alias in aliases:
            key = self.normalize_key(alias)
            if key and key not in seen:
                seen.add(key)
                out.append(alias)
        return out

    def _task_graph_aliases(self, *, result_pid: str, result_name: str, task_graph: dict[str, Any] | None) -> list[str]:
        if not isinstance(task_graph, dict):
            return []
        tasks = task_graph.get("tasks") if isinstance(task_graph.get("tasks"), list) else []
        result_keys = {x for x in {str(result_pid or "").strip(), str(result_name or "").strip()} if x}
        out: list[str] = []
        for ordinal, task in enumerate(tasks, start=1):
            if not isinstance(task, dict):
                continue
            task_keys = {
                str(task.get("participant_id") or "").strip(),
                str(task.get("id") or "").strip(),
                str(task.get("participant_display_name") or "").strip(),
                str(task.get("display_name") or "").strip(),
                str(task.get("name") or "").strip(),
                str(task.get("agent_name") or "").strip(),
                str(task.get("task_id") or "").strip(),
                str(task.get("source_step_id") or "").strip(),
            }
            task_keys = {x for x in task_keys if x}
            if result_keys and task_keys and not (result_keys & task_keys):
                continue
            out.extend([f"step{ordinal}", f"step_{ordinal}", f"step {ordinal}", f"stage{ordinal}", f"stage_{ordinal}", f"stage {ordinal}"])
            for key in task_keys:
                out.append(key)
                match = re.search(r"(\d+)", key)
                if match:
                    n = match.group(1)
                    out.extend([f"step{n}", f"step_{n}", f"step {n}", f"stage{n}", f"stage_{n}", f"stage {n}"])
        return out

    def resolve(self, value: Any, refs: dict[str, Any], path: str = "") -> TemplateResolution:
        if isinstance(value, dict):
            changed = False
            unresolved: list[dict[str, Any]] = []
            out: dict[str, Any] = {}
            for key, item in value.items():
                child = f"{path}.{key}" if path else str(key)
                resolved = self.resolve(item, refs, child)
                out[key] = resolved.value
                changed = changed or resolved.changed
                unresolved.extend(resolved.unresolved)
            return TemplateResolution(out, unresolved, changed)
        if isinstance(value, list):
            changed = False
            unresolved = []
            out_list = []
            for index, item in enumerate(value):
                child = f"{path}[{index}]" if path else f"[{index}]"
                resolved = self.resolve(item, refs, child)
                out_list.append(resolved.value)
                changed = changed or resolved.changed
                unresolved.extend(resolved.unresolved)
            return TemplateResolution(out_list, unresolved, changed)
        if not isinstance(value, str) or "{{" not in value or "}}" not in value:
            return TemplateResolution(value, [], False)
        matches = list(self._TEMPLATE_RE.finditer(value))
        if not matches:
            return TemplateResolution(value, [], False)
        unresolved: list[dict[str, Any]] = []
        if len(matches) == 1 and matches[0].span() == (0, len(value)):
            ref = matches[0].group(1).strip()
            resolved_value = refs.get(self.normalize_key(ref))
            if self.is_public_material(resolved_value):
                return TemplateResolution(resolved_value, [], True)
            unresolved.append({"path": path or "$", "reference": ref, "value_preview": value[:240]})
            return TemplateResolution(value, unresolved, False)

        def replace(match: re.Match[str]) -> str:
            ref = match.group(1).strip()
            resolved_value = refs.get(self.normalize_key(ref))
            if not self.is_public_material(resolved_value):
                unresolved.append({"path": path or "$", "reference": ref, "value_preview": value[:240]})
                return match.group(0)
            scalar = self.first_scalar(resolved_value)
            return scalar if scalar else match.group(0)

        new_value = self._TEMPLATE_RE.sub(replace, value)
        return TemplateResolution(new_value, unresolved, new_value != value)
