from __future__ import annotations

from typing import Any


class GraphSelfCheck:
    """Validates graph completion using structural evidence, not status alone."""

    SUCCESS_STATUSES = {"completed", "passed", "succeeded", "ok"}

    def validate(self, *, original_request: dict[str, Any] | str | None, partition: Any, scheduler_summary: dict[str, Any], final_output: dict[str, Any] | str | None) -> dict[str, Any]:
        issues: list[dict[str, Any]] = []
        dataflow = getattr(partition, "dataflow_graph", {}) if partition is not None else {}
        execution = getattr(partition, "execution_graph", {}) if partition is not None else {}
        edges = dataflow.get("edges") if isinstance(dataflow, dict) else []
        nodes = execution.get("nodes") if isinstance(execution, dict) else []
        completed = set(scheduler_summary.get("completed") or []) if isinstance(scheduler_summary, dict) else set()
        bound_inputs = scheduler_summary.get("bound_inputs") if isinstance(scheduler_summary, dict) else {}

        for node in nodes if isinstance(nodes, list) else []:
            node_id = str((node or {}).get("node_id") or "")
            if node_id and node_id not in completed:
                issues.append({"code": "node_not_completed", "node_id": node_id})

        for edge in edges if isinstance(edges, list) else []:
            src = str(edge.get("from") or "")
            dst = str(edge.get("to") or "")
            if not src or not dst:
                issues.append({"code": "edge_missing_endpoint", "edge": edge})
                continue
            if src not in completed:
                issues.append({"code": "edge_source_not_completed", "from": src, "to": dst})
            if dst in completed and src not in (bound_inputs.get(dst) or {}):
                issues.append({"code": "edge_output_not_bound", "from": src, "to": dst})

        request_constraints = self._request_constraints(original_request)
        final_text = self._final_text(final_output)
        if request_constraints.get("non_empty_final") and not final_text.strip():
            issues.append({"code": "final_output_empty"})
        min_chars = request_constraints.get("min_chars")
        if isinstance(min_chars, int) and len(final_text) < min_chars:
            issues.append({"code": "final_output_too_short", "expected_min_chars": min_chars, "actual_chars": len(final_text)})
        required_items = request_constraints.get("required_items")
        if isinstance(required_items, list):
            missing = [str(item) for item in required_items if str(item) and str(item) not in final_text]
            if missing:
                issues.append({"code": "final_output_missing_required_items", "missing_items": missing})

        repair_plan = self._repair_plan(issues)
        return {
            "status": "passed" if not issues else "failed",
            "issue_count": len(issues),
            "issues": issues,
            "repair_plan": repair_plan,
        }

    def _repair_plan(self, issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
        plan: list[dict[str, Any]] = []
        seen: set[str] = set()
        for issue in issues:
            code = str(issue.get("code") or "")
            if not code or code in seen:
                continue
            seen.add(code)
            if code.startswith("edge_"):
                plan.append({"action": "rebuild_or_rebind_dataflow", "reason": code})
            elif code == "node_not_completed":
                plan.append({"action": "rerun_unfinished_nodes", "reason": code})
            elif code.startswith("final_output"):
                plan.append({"action": "rerun_final_synthesis", "reason": code})
            else:
                plan.append({"action": "inspect_runtime_state", "reason": code})
        return plan

    def _request_constraints(self, request: dict[str, Any] | str | None) -> dict[str, Any]:
        if isinstance(request, dict):
            constraints = request.get("acceptance_constraints") or request.get("constraints") or {}
            return constraints if isinstance(constraints, dict) else {}
        return {"non_empty_final": True} if isinstance(request, str) and request.strip() else {}

    def _final_text(self, final_output: dict[str, Any] | str | None) -> str:
        if isinstance(final_output, str):
            return final_output
        if isinstance(final_output, dict):
            for key in ("final_answer", "message", "content", "output"):
                value = final_output.get(key)
                if isinstance(value, str):
                    return value
        return ""
