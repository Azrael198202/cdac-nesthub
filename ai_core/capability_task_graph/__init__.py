"""Capability TaskGraph compiler for runtime acquisition.

This package is intentionally capability-neutral.  It converts a long runtime
capability request/blueprint into small execution stages that auxiliary_brain can
materialize, validate, repair, and log independently.
"""

from .capability_task_graph_compiler import CapabilityTaskGraphCompiler

__all__ = ["CapabilityTaskGraphCompiler"]
