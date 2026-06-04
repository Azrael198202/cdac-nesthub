"""Compatibility namespace for the generic feedback-repair layer.

The implementation stays under ai_core.runtime.self_repair because it is part of
runtime governance, but this package exposes the phase name used by the system
architecture.  No capability-specific or business-specific logic belongs here.
"""

from ai_core.runtime.self_repair.repair_orchestrator import FeedbackRepairOrchestrator
from ai_core.runtime.self_repair.execution_failure_repair import (
    ExecutionFailureDiagnosis,
    ExecutionFailureRepairClassifier,
)

__all__ = [
    "FeedbackRepairOrchestrator",
    "ExecutionFailureDiagnosis",
    "ExecutionFailureRepairClassifier",
]
