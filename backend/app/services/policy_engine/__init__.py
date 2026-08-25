"""Policy Engine — deterministic evaluation of security/business policies.

Evaluates policies against StructuredIntent, TransactionProposal, and DriftResult.
Produces PASS / TRIGGERED / UNKNOWN / INVALID_POLICY per policy.

Does NOT make ALLOW / REVIEW / BLOCK decisions — that belongs to the future Decision Engine.
"""
