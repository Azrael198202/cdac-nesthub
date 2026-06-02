"""Auxiliary-brain runtime capability acquisition package.

ai_core emits NeedCapability events and stays responsible for generic
understanding, planning, validation, execution orchestration, and synthesis.
This package owns capability acquisition, artifact generation, sandbox
validation, execution verification, and registry updates.
"""

from .acquisition_router import RuntimeCapabilityGapImplementer

__all__ = ["RuntimeCapabilityGapImplementer"]
