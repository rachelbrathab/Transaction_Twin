"""Adaptive Risk Calibration & Decision Intelligence Engine.

Deterministic, read-only analysis of historical decision patterns,
signal quality, policy behavior, and system calibration.

No database access in core engine. No ML. No LLM. No external calls.
"""

from app.services.calibration_engine.engine import CalibrationEngine

__all__ = ["CalibrationEngine"]
