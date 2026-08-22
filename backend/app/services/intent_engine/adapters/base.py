"""Abstract LLM adapter interface.

The Intent Engine depends on this interface, never on a specific provider.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel


class ProviderInfo(BaseModel):
    """Information about the LLM provider used."""

    provider: str
    model: str
    latency_ms: int = 0
    tokens_used: int = 0


class AdapterResult(BaseModel):
    """Result from an LLM adapter."""

    success: bool
    raw_output: dict[str, Any] | None = None
    provider_info: ProviderInfo | None = None
    error: str | None = None


class LLMAdapter(ABC):
    """Abstract interface for LLM adapters.

    All adapters must implement parse_intent and health_check.
    The Intent Engine depends only on this interface.
    """

    @abstractmethod
    async def parse_intent(
        self,
        canonical_request: str,
        resolved_currency: str | None,
        transaction_type_hint: str | None,
        reference_timestamp: str,
        prompt_version: str,
    ) -> AdapterResult:
        """Parse a canonical request into structured intent JSON.

        Returns AdapterResult with raw_output dict or error.
        """

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the provider is available."""

    def get_provider_info(self) -> ProviderInfo:
        """Return information about this provider."""
        return ProviderInfo(provider="unknown", model="unknown")
