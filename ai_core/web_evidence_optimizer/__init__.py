"""Compatibility facade for migrated implementation.

The implementation for ai_core/web_evidence_optimizer now lives in auxiliary_brain/web_evidence_optimizer.
This facade preserves existing imports while keeping ai_core focused on generic brain/runtime contracts.
"""
from auxiliary_brain.web_evidence_optimizer.__init__ import *  # noqa: F401,F403
