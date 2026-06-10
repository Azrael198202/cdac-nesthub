"""Compatibility facade for migrated implementation.

The implementation for ai_core/runtime/learning now lives in auxiliary_brain/runtime/learning.
This facade preserves existing imports while keeping ai_core focused on generic brain/runtime contracts.
"""
from auxiliary_brain.runtime.learning.__init__ import *  # noqa: F401,F403
