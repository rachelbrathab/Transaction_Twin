"""Calibration Runtime — strongly typed models.

Defines the data structures for resolved effective configuration
and validation outcomes. All models are Pydantic v2, frozen, and
deterministic.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ValidationOutcome(BaseModel, frozen=True):
    """Result of validating a single calibration parameter."""

    parameter_name: str
    category: str
    is_valid: bool
    current_value: float | None = None
    proposed_value: float | None = None
    error: str | None = None


class RuntimeCalibrationConfig(BaseModel, frozen=True):
    """Raw calibration configuration extracted from an active version.

    This represents the proposed calibration values before validation.
    """

    version_id: str
    source_window_days: int = 0
    parameter_snapshot: dict = Field(default_factory=dict)
    is_active: bool = False
    activated_at: str | None = None


class EffectiveCalibrationConfig(BaseModel, frozen=True):
    """The EFFECTIVE configuration after validation and resolution.

    This is the safe, validated configuration that may optionally be
    consumed by the Risk Engine. It contains only validated parameters
    that pass all safety checks.

    When calibration is not active or is invalid, this config contains
    only the existing defaults with calibration_active=False.
    """

    calibration_active: bool = False
    source_version_id: str = ""

    # Signal weights (validated, sums to ~1.0)
    signal_weights: dict[str, float] = Field(default_factory=dict)

    # Risk level thresholds (validated, ordered, in [0,1])
    risk_level_thresholds: dict[str, float] = Field(default_factory=dict)

    # Confidence reductions (validated, in safe bounds)
    confidence_reductions: dict[str, float] = Field(default_factory=dict)

    # Confidence bounds (validated, floor < ceiling)
    confidence_floor: float = 0.1
    confidence_ceiling: float = 1.0

    # Validation metadata
    validation_passed: bool = False
    validation_errors: list[str] = Field(default_factory=list)
    validation_warnings: list[str] = Field(default_factory=list)

    # Deterministic metadata
    parameters_applied: list[str] = Field(default_factory=list)
    parameters_rejected: list[str] = Field(default_factory=list)
