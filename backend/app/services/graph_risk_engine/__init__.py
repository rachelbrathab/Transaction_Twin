"""Graph Risk Engine — deterministic network intelligence layer.

Provides explainable network risk signals by analyzing graph relationships
between agents, merchants, and transactions. Database-independent core engine.
"""

from app.services.graph_risk_engine.engine import GraphRiskEngine

__all__ = ["GraphRiskEngine"]
