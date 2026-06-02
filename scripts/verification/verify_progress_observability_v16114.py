from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from ai_core.runtime.observability.runtime_console import emit_console_event, set_current_run_id, reset_current_run_id
from runtime_assets.seeds.capability_planners.default_capability_planner import _deterministic_blueprint_fallback


def test_console_run_id_binding() -> None:
    run_id = "verify_run_scope_001"
    token = set_current_run_id(run_id)
    try:
        emit_console_event(
            area="capability_acquisition",
            event="BlueprintPlanner",
            status="running",
            message="Blueprint planning started",
            data={"stage_label": "BlueprintPlanner", "action": "Generating compact blueprint"},
        )
    finally:
        reset_current_run_id(token)
    log = Path("runtime/logs/runtime_console.jsonl")
    assert log.exists(), "runtime console log should exist"
    last = None
    for line in log.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            item = json.loads(line)
        except Exception:
            continue
        if item.get("event") == "BlueprintPlanner":
            last = item
    assert last is not None, "BlueprintPlanner event should be emitted"
    assert last.get("data", {}).get("run_id") == run_id, "event must be correlated with current UI run id"


def test_structural_fallback_extracts_only_schema_sections() -> None:
    request = """
    Acquire runtime capability.
    Store connection values through Agent Studio UI.
    Input schema must include:
    * alpha
    * beta_value
    Connection schema must include only:
    * endpoint_value
    Secret schema must include only:
    * credential_value
    """
    payload = _deterministic_blueprint_fallback(request_text=request, identity={}, evidence={}, model_attempt={"reason": "test"})
    bp = payload["blueprint"]
    assert bp["required_inputs"] == ["alpha", "beta_value"]
    assert bp["required_connection_fields"] == ["endpoint_value"]
    assert bp["required_secret_fields"] == ["credential_value"]
    assert "store" not in bp["required_connection_fields"], "prose words must not become schema fields"


if __name__ == "__main__":
    test_console_run_id_binding()
    test_structural_fallback_extracts_only_schema_sections()
    print("progress observability verification passed")
