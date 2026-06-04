from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_core.feedback_repair import ExecutionFailureRepairClassifier, FeedbackRepairOrchestrator

ROOT = Path(__file__).resolve().parents[1]
SCAN_PATHS = [
    ROOT / "ai_core" / "runtime" / "self_repair",
    ROOT / "ai_core" / "feedback_repair",
    ROOT / "auxiliary_brain" / "feedback_repair",
    ROOT / "auxiliary_brain" / "capability_acquisition" / "repair_coordinator.py",
]

# These terms are examples of capability/provider/domain-specific vocabulary
# that must not appear in the generic feedback-repair layer. Generated tools,
# capability acquisition templates, and runtime artifacts are deliberately not
# scanned by this boundary check.
DISALLOWED_TERMS = [
    "smtp",
    "gmail",
    "weather",
    "forecast",
    "flight",
    "booking",
    "reservation",
]


def _iter_text_files(path: Path):
    if path.is_file():
        yield path
        return
    if path.exists():
        for item in path.rglob("*"):
            if item.is_file() and item.suffix.lower() in {".py", ".json", ".yaml", ".yml", ".md", ".txt"}:
                yield item


def verify_no_business_terms() -> None:
    violations: list[str] = []
    for base in SCAN_PATHS:
        for file_path in _iter_text_files(base):
            text = file_path.read_text(encoding="utf-8", errors="ignore").casefold()
            for term in DISALLOWED_TERMS:
                if term in text:
                    violations.append(f"{file_path.relative_to(ROOT)} contains disallowed term: {term}")
    if violations:
        raise AssertionError("\n".join(violations))


def verify_generic_behavior() -> None:
    trace_dir = ROOT / "runtime" / "traces" / "feedback_repair"
    if trace_dir.exists():
        shutil.rmtree(trace_dir)

    classifier = ExecutionFailureRepairClassifier()

    parameter = classifier.classify(
        result={"status": "error", "error": {"code": "tool_input_schema_validation_failed", "message": "required value is missing"}},
        tool_spec={},
    )
    assert parameter.category == "parameter_problem"

    secret = classifier.classify(
        result={"status": "error", "error": {"code": "tool_execution_failed", "message": "authentication credential not accepted"}},
        tool_spec={},
    )
    assert secret.category == "secret_problem"

    external = classifier.classify(
        result={"status": "error", "error": {"code": "tool_execution_failed", "message": "remote endpoint timeout"}},
        tool_spec={},
    )
    assert external.category == "external_service_problem"

    implementation = classifier.classify(
        result={"status": "error", "error": {"code": "tool_execution_failed", "message": "ImportError: module load failed"}},
        tool_spec={"implementation": {"type": "runtime_python"}},
    )
    assert implementation.category == "tool_implementation_problem"

    orch = FeedbackRepairOrchestrator()
    proposal = orch.propose_for_tool_result(
        run_id="verify_feedback_repair_generic_boundary",
        tool_id="generic_runtime_tool",
        profile_id="default",
        result={"status": "error", "error": {"code": "tool_input_schema_validation_failed", "message": "required value is missing"}},
        tool_spec={"tool_id": "generic_runtime_tool", "implementation": {"type": "runtime_python"}},
        input_payload={},
        expected_contract={"input_schema": {"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"]}},
        runtime_state={},
    )
    assert proposal["requires_user_confirmation"] is True
    assert proposal["diagnosis"]["category"] == "parameter_problem"
    trace = trace_dir / "verify_feedback_repair_generic_boundary.jsonl"
    assert trace.exists(), trace
    events = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert {"failure_received", "failure_classified", "repair_proposal_created"} <= {event["stage"] for event in events}


def main() -> None:
    verify_no_business_terms()
    verify_generic_behavior()
    print("feedback repair generic boundary verification passed")


if __name__ == "__main__":
    main()
