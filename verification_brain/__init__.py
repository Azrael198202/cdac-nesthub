from verification_brain.contracts import VerificationExpectation, VerificationResult
from verification_brain.engine import RuntimeVerificationBrain
from verification_brain.model_verification_loop import ModelVerificationLoop, ModelVerificationLoopConfig, ConvergenceController
from verification_brain.runtime_validator import RuntimeSerializationValidator, RuntimeSerializationValidationResult
from verification_brain.settings import VerificationBrainSettings, VerificationBrainSettingsStore

__all__ = [
    "VerificationExpectation",
    "VerificationResult",
    "RuntimeVerificationBrain",
    "ModelVerificationLoop",
    "ModelVerificationLoopConfig",
    "ConvergenceController",
    "VerificationBrainSettings",
    "VerificationBrainSettingsStore",
    "RuntimeSerializationValidator",
    "RuntimeSerializationValidationResult",
]

try:
    from verification_brain.foundation import RuntimeFailureReport, RuntimeVerificationFoundation
    __all__.extend(["RuntimeFailureReport", "RuntimeVerificationFoundation"])
except Exception:
    # Foundation depends on optional runtime repair/auxiliary packages.  Keep the
    # core verification brain importable even when those optional layers are not
    # present in a trimmed source package.
    RuntimeFailureReport = None  # type: ignore
    RuntimeVerificationFoundation = None  # type: ignore
