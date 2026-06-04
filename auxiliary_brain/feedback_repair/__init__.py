"""Auxiliary-brain feedback-repair namespace.

This package owns implementation-level repair lifecycle orchestration outside
ai_core.  The concrete repair target is derived from trace contracts, not from
hard-coded capability names.
"""

from auxiliary_brain.capability_acquisition.repair_coordinator import AuxiliaryCapabilityRepairCoordinator

__all__ = ["AuxiliaryCapabilityRepairCoordinator"]
