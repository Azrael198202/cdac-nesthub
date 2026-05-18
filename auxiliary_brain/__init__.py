"""Parallel auxiliary brain runtime package.

This package is intentionally separated from ai_core. ai_core remains the
main controller, while auxiliary_brain provides a neutral runtime for
runtime-generated participant communities. Concrete domain labels and behavior
belong under runtime/generated, not in this source package.
"""

from .runtime import AuxiliaryBrainRuntime

__all__ = ["AuxiliaryBrainRuntime"]
