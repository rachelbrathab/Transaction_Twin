"""API v1 router.

Aggregates all versioned endpoint routers.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    agents,
    analytics,
    audit_vault,
    auth,
    calibration_intelligence,
    comparisons,
    health,
    history,
    intents,
    outcomes,
    policies,
    policy_crud,
    reviews,
    risk_intelligence,
    simulate,
    transaction_list,
    transactions,
)

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(health.router, tags=["Health"])
api_router.include_router(agents.router, tags=["Agents"])
api_router.include_router(intents.router, tags=["Intents"])
api_router.include_router(comparisons.router, tags=["Comparisons"])
api_router.include_router(policies.router, tags=["Policy Evaluation"])
api_router.include_router(policy_crud.router, tags=["Policies"])
api_router.include_router(transactions.router, tags=["Transaction Decision"])
api_router.include_router(transaction_list.router, tags=["Transactions"])
api_router.include_router(outcomes.router, tags=["Outcomes"])
api_router.include_router(reviews.router, tags=["Reviews"])
api_router.include_router(history.router, tags=["Transaction History"])
api_router.include_router(risk_intelligence.router, tags=["Risk Intelligence"])
api_router.include_router(audit_vault.router, tags=["Audit Vault"])
api_router.include_router(analytics.router, tags=["Analytics"])
api_router.include_router(simulate.router, tags=["Simulate Outcome"])
api_router.include_router(
    calibration_intelligence.router,
    tags=["Calibration Intelligence"],
)
