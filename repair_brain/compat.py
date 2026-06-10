from __future__ import annotations

# Compatibility exports for code that still imports the old ai_core repair
# orchestrator directly. Existing runtime behavior remains unchanged.
from auxiliary_brain.runtime.self_repair.repair_orchestrator import FeedbackRepairOrchestrator
from auxiliary_brain.runtime.self_repair.execution_failure_repair import (
    ExecutionFailureDiagnosis,
    ExecutionFailureRepairClassifier,
)

__all__ = [
    "FeedbackRepairOrchestrator",
    "ExecutionFailureDiagnosis",
    "ExecutionFailureRepairClassifier",
]
