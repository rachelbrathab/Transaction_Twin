"""Risk Engine — deterministic, explainable risk assessment.

Consumes pre-computed outputs from Intent Engine, Transaction Twin,
Policy Engine, and trust signals to produce a RiskResult.

Does NOT make ALLOW/REVIEW/BLOCK decisions.
Does NOT persist RiskAssessment.
Does NOT query the database.
Does NOT call external APIs or LLMs.
"""

from app.services.risk_engine.engine import RiskEngine

__all__ = ["RiskEngine"]
