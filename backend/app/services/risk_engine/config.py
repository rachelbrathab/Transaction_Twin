"""Risk Engine — runtime configuration.

Provides an optional typed configuration that overrides the default
Risk Engine constants. The Risk Engine itself never mutates its
module-level constants; instead, this config object supplies the
effective values at evaluation time.

CRITICAL SAFETY:
- This module NEVER modifies SIGNAL_WEIGHTS, RISK_LEVEL_THRESHOLDS,
  CONFIDENCE_REDUCTIONS, CONFIDENCE_FLOOR, or CONFIDENCE_CEILING.
- When config is None, the Risk Engine uses exact existing defaults.
- When config is provided, it is used as-is (already validated).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.services.risk_engine.constants import (
    CONFIDENCE_CEILING,
    CONFIDENCE_FLOOR,
    CONFIDENCE_REDUCTIONS,
    RISK_LEVEL_THRESHOLDS,
    SIGNAL_WEIGHTS,
)
from app.services.risk_engine.models import RiskLevel, RiskSignalType


class RiskEngineConfig(BaseModel, frozen=True):
    """Optional runtime configuration for Risk Engine evaluation.

    When provided, overrides the module-level defaults.
    When None is passed to evaluate(), exact defaults are used.
    """

    signal_weights: dict[str, float] = Field(default_factory=dict)
    risk_level_thresholds: dict[str, float] = Field(default_factory=dict)
    confidence_reductions: dict[str, float] = Field(default_factory=dict)
    confidence_floor: float = CONFIDENCE_FLOOR
    confidence_ceiling: float = CONFIDENCE_CEILING
    calibration_active: bool = False
    calibration_version_id: str = ""


def get_default_risk_engine_config() -> RiskEngineConfig:
    """Return a config representing exact existing defaults.

    This produces a fresh, independent copy of the current
    Risk Engine configuration. The values are identical to
    the module-level constants.
    """
    return RiskEngineConfig(
        signal_weights={k.value: v for k, v in SIGNAL_WEIGHTS.items()},
        risk_level_thresholds={
            level.value: threshold
            for threshold, level in RISK_LEVEL_THRESHOLDS
        },
        confidence_reductions=dict(CONFIDENCE_REDUCTIONS),
        confidence_floor=CONFIDENCE_FLOOR,
        confidence_ceiling=CONFIDENCE_CEILING,
        calibration_active=False,
    )


def get_effective_signal_weight(
    signal_type: RiskSignalType,
    config: RiskEngineConfig | None = None,
) -> float:
    """Get the effective signal weight, using config if provided, else default."""
    if config is not None and config.signal_weights:
        weight = config.signal_weights.get(signal_type.value)
        if weight is not None:
            return weight
    return SIGNAL_WEIGHTS.get(signal_type, 0.0)


def get_effective_confidence_reduction(
    key: str,
    config: RiskEngineConfig | None = None,
) -> float:
    """Get the effective confidence reduction, using config if provided, else default."""
    if config is not None and config.confidence_reductions:
        reduction = config.confidence_reductions.get(key)
        if reduction is not None:
            return reduction
    return CONFIDENCE_REDUCTIONS.get(key, 0.0)


def get_effective_confidence_floor(
    config: RiskEngineConfig | None = None,
) -> float:
    """Get the effective confidence floor."""
    if config is not None:
        return config.confidence_floor
    return CONFIDENCE_FLOOR


def get_effective_confidence_ceiling(
    config: RiskEngineConfig | None = None,
) -> float:
    """Get the effective confidence ceiling."""
    if config is not None:
        return config.confidence_ceiling
    return CONFIDENCE_CEILING


def get_effective_risk_level_thresholds(
    config: RiskEngineConfig | None = None,
) -> list[tuple[float, RiskLevel]]:
    """Get the effective risk level thresholds.

    Returns a list of (threshold, RiskLevel) tuples sorted descending,
    matching the format of the original RISK_LEVEL_THRESHOLDS constant.
    """
    if config is not None and config.risk_level_thresholds:
        level_map = {level.value: level for _, level in RISK_LEVEL_THRESHOLDS}
        result = []
        for level_str, threshold in config.risk_level_thresholds.items():
            if level_str in level_map:
                result.append((threshold, level_map[level_str]))
        # Sort descending by threshold
        result.sort(key=lambda x: x[0], reverse=True)
        return result
    return RISK_LEVEL_THRESHOLDS
