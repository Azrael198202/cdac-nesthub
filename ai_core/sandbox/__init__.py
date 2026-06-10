"""Compatibility facade for migrated implementation.

The implementation for ai_core/sandbox now lives in auxiliary_brain/sandbox.
This facade preserves existing imports while keeping ai_core focused on generic brain/runtime contracts.
"""
from auxiliary_brain.sandbox.__init__ import *  # noqa: F401,F403
