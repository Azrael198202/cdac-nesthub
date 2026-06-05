"""Compatibility namespace for the generic feedback-repair layer.

New code should import repair-brain contracts from ``repair_brain``.  This
package remains as a stable compatibility facade so current runtime behavior and
imports do not change during the gradual brain separation.
"""

from repair_brain import (
    ExecutionFailureDiagnosis,
    ExecutionFailureRepairClassifier,
    FeedbackRepairOrchestrator,
    RepairPlan,
    RepairRequest,
    RuntimeRepairBrain,
)

__all__ = [
    "FeedbackRepairOrchestrator",
    "ExecutionFailureDiagnosis",
    "ExecutionFailureRepairClassifier",
    "RuntimeRepairBrain",
    "RepairPlan",
    "RepairRequest",
]
