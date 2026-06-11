from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BindingCompiler:
    """Compiles dataflow bindings into structured records.

    It intentionally rejects runtime template strings as the durable binding
    source. Execution resolves binding ids instead of parsing text templates.
    """

    def compile(self, steps: list[dict[str, Any]], task_graph: dict[str, Any]) -> list[dict[str, Any]]:
        bindings: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str, str]] = set()
        aliases = self._step_aliases(steps)
        graph_bindings = task_graph.get("workflow_bindings") if isinstance(task_graph.get("workflow_bindings"), list) else []
        for item in graph_bindings:
            self._append_binding(bindings, seen, item, aliases)
        for step in steps:
            target_step = str(step.get("step_id") or "")
            for item in ((step.get("binding_contract") or {}).get("bindings") or []):
                if not isinstance(item, dict):
                    continue
                enriched = dict(item)
                enriched.setdefault("target_step", target_step)
                self._append_binding(bindings, seen, enriched, aliases)
            for upstream in step.get("depends_on") or []:
                source = aliases.get(str(upstream).strip(), self._normalize_step_ref(str(upstream)))
                target = target_step
                key = (source, "presentation.final_answer", target, "body")
                if source and target and key not in seen:
                    seen.add(key)
                    bindings.append({
                        "binding_id": f"binding_{len(bindings) + 1:03d}",
                        "source_step": source,
                        "source_field": "presentation.final_answer",
                        "target_step": target,
                        "target_field": "body",
                        "resolver": "ResolveBinding",
                        "template_parsing_enabled": False,
                    })
        return bindings

    def _append_binding(self, out: list[dict[str, Any]], seen: set[tuple[str, str, str, str]], item: Any, aliases: dict[str, str] | None = None) -> None:
        if not isinstance(item, dict):
            return
        aliases = aliases or {}
        raw_source = str(item.get("source_step") or item.get("from_step") or item.get("source") or "").strip()
        raw_target = str(item.get("target_step") or item.get("to_step") or item.get("target") or "").strip()
        source_step = aliases.get(raw_source, self._normalize_step_ref(raw_source))
        target_step = aliases.get(raw_target, self._normalize_step_ref(raw_target))
        source_field = str(item.get("source_field") or item.get("from_field") or "presentation.final_answer").strip()
        target_field = str(item.get("target_field") or item.get("to_field") or "body").strip()
        if not source_step or not target_step:
            return
        key = (source_step, source_field, target_step, target_field)
        if key in seen:
            return
        seen.add(key)
        out.append({
            "binding_id": str(item.get("binding_id") or f"binding_{len(out) + 1:03d}"),
            "source_step": source_step,
            "source_field": source_field,
            "target_step": target_step,
            "target_field": target_field,
            "resolver": "ResolveBinding",
            "template_parsing_enabled": False,
        })

    def _step_aliases(self, steps: list[dict[str, Any]]) -> dict[str, str]:
        aliases: dict[str, str] = {}
        for step in steps:
            if not isinstance(step, dict):
                continue
            step_id = str(step.get("step_id") or "").strip()
            if not step_id:
                continue
            for value in (step_id, step.get("participant_id"), (step.get("raw_step_ref") or {}).get("participant_id") if isinstance(step.get("raw_step_ref"), dict) else None, (step.get("raw_step_ref") or {}).get("source_step_id") if isinstance(step.get("raw_step_ref"), dict) else None):
                text = str(value or "").strip()
                if text:
                    aliases[text] = step_id
        return aliases

    def _normalize_step_ref(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if text.startswith("step_"):
            return text
        if text.isdigit():
            return f"step_{int(text):03d}"
        return text
