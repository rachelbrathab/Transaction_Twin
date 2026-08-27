"""Calibration Runtime — safe configuration resolver.

Provides a read-only-at-runtime configuration resolver that determines
the effective risk-engine parameters from an active calibration version.

CRITICAL SAFETY BOUNDARY:
- This module NEVER mutates existing Risk Engine constants.
- This module provides a PURE resolver function.
- The Risk Engine remains unchanged unless explicitly integrated.
- No eval, exec, subprocess, LLM, or payment execution.
"""

from app.services.calibration_runtime.models import (
    EffectiveCalibrationConfig,
    RuntimeCalibrationConfig,
    ValidationOutcome,
)
from app.services.calibration_runtime.resolver import (
    resolve_effective_config,
)
from app.services.calibration_runtime.validation import (
    validate_calibration_parameters,
)

__all__ = [
    "EffectiveCalibrationConfig",
    "RuntimeCalibrationConfig",
    "ValidationOutcome",
    "resolve_effective_config",
    "validate_calibration_parameters",
]
