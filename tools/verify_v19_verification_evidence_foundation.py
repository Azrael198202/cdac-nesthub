from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from verification_brain import RuntimeVerificationFoundation


def main() -> None:
    task_graph = {
        "task_name": "GenericVerificationTask",
        "graph_id": "graph_generic_verification",
        "selected_participant_ids": ["participant_a"],
        "runtime_parameters": {"x": "{{upstream.value}}"},
    }
    participants = [{"participant_id": "participant_a", "name": "Participant A"}]
    run_payload = {
        "run_id": "delegation_run_verify_v19",
        "task_name": "GenericVerificationTask",
        "graph_id": "graph_generic_verification",
        "status": "completed",
        "agent_results": [{"participant_id": "participant_a", "status": "completed"}],
        "synthesis": {"final_answer": "{{upstream.value}}"},
    }
    foundation = RuntimeVerificationFoundation()
    report = foundation.inspect_run(task_graph=task_graph, participants=participants, run_payload=run_payload, stage="unit_verification")
    assert report is not None, "unresolved template must produce a failure report"
    assert report.failure_class == "template_resolution_problem", report.to_dict()
    assert report.suggested_owner == "ai_core", report.to_dict()
    assert report.evidence_path, report.to_dict()
    assert Path(report.evidence_path).exists(), report.evidence_path
    listed = foundation.list_reports(limit=20)
    assert any(item.get("report_id") == report.report_id for item in listed), report.report_id
    print(json.dumps({"ok": True, "report_id": report.report_id, "failure_class": report.failure_class}, ensure_ascii=False))


if __name__ == "__main__":
    main()
