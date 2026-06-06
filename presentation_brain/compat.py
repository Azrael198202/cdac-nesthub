from __future__ import annotations

# Compatibility shim for existing imports during the structural migration.
# New code should import PresentationBrain from presentation_brain.brain.
from presentation_brain.brain import PresentationBrain
from presentation_brain.contracts import PresentationRequest, PresentationResult

__all__ = ["PresentationBrain", "PresentationRequest", "PresentationResult"]
