import json
import tempfile
from pathlib import Path

from auxiliary_brain.capability_acquisition.acquisition_router import RuntimeCapabilityGapImplementer
from ai_core.runtime.state.manager import RuntimeStateManager


def test_entrypoint_smoke_runner_prints_and_validates_json_output():
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        tool_dir = root / "tool"
        tool_dir.mkdir()
        (tool_dir / "tool.py").write_text(
            "from datetime import datetime\n"
            "from zoneinfo import ZoneInfo\n"
            "def run(payload):\n"
            "    data = payload.get('input', {})\n"
            "    fmt = data.get('format', '%Y-%m-%d %H:%M')\n"
            "    tz = data.get('timezone', 'Asia/Tokyo')\n"
            "    return {'status': 'completed', 'data': {'runtime_value': datetime.now(ZoneInfo(tz)).strftime(fmt)}}\n",
            encoding="utf-8",
        )
        (tool_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "entrypoint": {"module": "tool.py", "function": "run"},
                    "verification_input": {"input": {"timezone": "Asia/Tokyo", "format": "%Y-%m-%d %H:%M"}},
                    "output_schema": {"type": "object", "properties": {"status": {"type": "string"}, "data": {"type": "object"}}},
                }
            ),
            encoding="utf-8",
        )
        result = RuntimeCapabilityGapImplementer()._artifact_entrypoint_smoke_test(
            {"tool_dir": str(tool_dir), "manifest_path": str(tool_dir / "manifest.json")}
        )
    assert result["passed"] is True
    assert result["contract"]["passed"] is True


def test_terminal_step_event_is_projected_as_100_percent():
    with tempfile.TemporaryDirectory() as raw:
        manager = RuntimeStateManager(state_dir=Path(raw))
        manager.start_run("run_projection", title="projection")
        manager.emit(run_id="run_projection", step_id="stage", status="running", title="Stage", progress=15)
        completed = manager.emit(run_id="run_projection", step_id="stage", status="completed", title="Stage", progress=86)
        state = manager.get_run("run_projection")
    assert completed["progress"] == 100.0
    step = next(item for item in state["steps"] if item["step_id"] == "stage")
    assert step["status"] == "completed"
    assert step["progress"] == 100.0
