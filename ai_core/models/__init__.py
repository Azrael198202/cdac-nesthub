"""Compatibility facade for migrated implementation.

The implementation for ai_core/models now lives in auxiliary_brain/models.
This facade preserves existing imports while keeping ai_core focused on generic brain/runtime contracts.
"""
from auxiliary_brain.models.__init__ import *  # noqa: F401,F403
