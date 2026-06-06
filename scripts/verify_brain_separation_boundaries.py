from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evidence_engine import EvidenceRequest, RuntimeEvidenceCollector
from memory_brain import MemoryRecord, RuntimeMemoryStore
from repair_brain import RepairRequest, RuntimeRepairBrain
from task_runtime import TaskRuntimeRevision
from verification_brain import RuntimeVerificationBrain


def main() -> None:
    verifier = RuntimeVerificationBrain()
    failed = verifier.verify(output={"body": "{{unresolved}}"})
    assert not failed.passed, failed.to_dict()
    passed = verifier.verify(output={"body": "resolved"})
    assert passed.passed, passed.to_dict()

    collector = RuntimeEvidenceCollector(roots=[ROOT / "runtime" / "traces"])
    package = collector.collect(EvidenceRequest(run_id="nonexistent-run", max_lines_per_file=10))
    assert isinstance(package.summary, dict)

    store = RuntimeMemoryStore(root=ROOT / "runtime" / "generated" / "_verify_memory_brain")
    result = store.remember(MemoryRecord(memory_type="verify", category="boundary", summary="ok"))
    assert result["ok"] is True
    assert store.recall(category="boundary", limit=1)

    repair = RuntimeRepairBrain()
    plan = repair.analyze(RepairRequest(
        run_id="verify-run",
        component="generic_component",
        failure={"error": {"code": "schema_validation_failed", "message": "missing required value"}},
        context={},
    ))
    assert plan.category == "parameter_problem", plan.to_dict()

    revision = TaskRuntimeRevision(
        task_name="ExampleTask",
        task_revision=1,
        graph_revision=1,
        plan_revision=1,
        active_revision_id="rev_1",
    )
    assert revision.to_dict()["task_name"] == "ExampleTask"
    print("brain_separation_boundaries: passed")


if __name__ == "__main__":
    main()
