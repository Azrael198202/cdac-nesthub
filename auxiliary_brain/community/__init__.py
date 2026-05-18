"""Generic runtime community primitives.

This package is intentionally domain-neutral. It provides lifecycle,
message exchange, shared state, persistence, and execution primitives for
runtime-generated participants. Domain-specific names and behaviors belong
under runtime/generated, not inside ai_core.
"""

from .models import (
    RuntimeAgentDefinition,
    RuntimeCommunityDefinition,
    RuntimeTaskDefinition,
    RuntimeTaskEdge,
    RuntimeActivation,
    RuntimeDispatchResult,
)
from .registry import RuntimeCommunityRegistry
from .message_bus import RuntimeMessageBus
from .blackboard import RuntimeBlackboard
from .community_runtime import RuntimeCommunityEngine
from .builder import RuntimeCommunityBuilder

__all__ = [
    "RuntimeAgentDefinition",
    "RuntimeCommunityDefinition",
    "RuntimeTaskDefinition",
    "RuntimeTaskEdge",
    "RuntimeActivation",
    "RuntimeDispatchResult",
    "RuntimeCommunityRegistry",
    "RuntimeMessageBus",
    "RuntimeBlackboard",
    "RuntimeCommunityEngine",
    "RuntimeCommunityBuilder",
]
