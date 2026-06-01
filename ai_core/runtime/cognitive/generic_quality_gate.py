from __future__ import annotations

import json
from typing import Any


class GenericQualityGate:
    """Generic output guard for runtime graph nodes.

    The gate validates structure and lifecycle constraints only.  It does not
    know task domains, tool names, protocols, people, places, or example data.
    """

    def validate_node_output(self, *, node_id: str, output: Any, graph_policy: dict[str, Any]) -> dict[str, Any]:
        gates = graph_policy.get("quality_gates") if isinstance(graph_policy.get("quality_gates"), dict) else {}
        json_nodes = set(str(x) for x in gates.get("json_nodes", []) if str(x).strip())
        locked_nodes = set(str(x) for x in gates.get("locked_plan_nodes", []) if str(x).strip())
        problems: list[dict[str, Any]] = []
        if str(node_id) in json_nodes and not isinstance(output, dict):
            parsed = self._parse_json_object(output)
            if not isinstance(parsed, dict):
                problems.append({"code": "expected_json_object", "severity": "error"})
            else:
                output = parsed
        if str(node_id) in locked_nodes and isinstance(output, dict):
            if output.get("replanned") is True or output.get("changed_execution_method") is True:
                problems.append({"code": "locked_plan_mutation", "severity": "error"})
        ok = not any(p.get("severity") == "error" for p in problems)
        return {"ok": ok, "problems": problems, "normalized_output": output}

    def _parse_json_object(self, value: Any) -> Any:
        if isinstance(value, dict):
            return value
        if not isinstance(value, str):
            return None
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
