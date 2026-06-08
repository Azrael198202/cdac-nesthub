from __future__ import annotations

# Compatibility shim: implementation moved to auxiliary_brain.
# ai_core may query registered capabilities through this facade, but capability
# blueprint generation/installation is owned by auxiliary_brain.
from auxiliary_brain.capability_acquisition.tools.runtime_tool_registry import *  # noqa: F401,F403
