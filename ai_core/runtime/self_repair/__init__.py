"""Compatibility facade for migrated implementation.

The implementation for ai_core/runtime/self_repair now lives in auxiliary_brain/runtime/self_repair.
This facade preserves existing imports while keeping ai_core focused on generic brain/runtime contracts.
"""
from auxiliary_brain.runtime.self_repair.__init__ import *  # noqa: F401,F403
