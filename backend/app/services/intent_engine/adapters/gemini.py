"""Gemini adapter — Google Gemini behind the LLMAdapter interface.

Requires GEMINI_API_KEY environment variable.
Gracefully handles missing keys — application works without LLM.
Uses google-genai SDK (current, non-deprecated).
"""

from __future__ import annotations

import json
import time

from app.services.intent_engine.adapters.base import AdapterResult, LLMAdapter, ProviderInfo

try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:
    genai = None  # type: ignore[assignment]
    genai_types = None  # type: ignore[assignment]

from app.core.config import get_settings


class GeminiAdapter(LLMAdapter):
    """Google Gemini adapter for intent parsing.

    Falls back gracefully if API key is missing or SDK is not installed.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "gemini-2.0-flash",
        timeout_seconds: float = 30.0,
        max_output_tokens: int = 2048,
    ) -> None:
        settings = get_settings()
        self._api_key = api_key or settings.gemini_api_key
        self._model_name = model_name
        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._configured = False
        self._client = None

        if self._api_key and genai is not None:
            try:
                self._client = genai.Client(api_key=self._api_key)
                self._configured = True
            except Exception:
                self._configured = False

    @property
    def is_available(self) -> bool:
        return self._configured and self._client is not None

    async def parse_intent(
        self,
        canonical_request: str,
        resolved_currency: str | None,
        transaction_type_hint: str | None,
        reference_timestamp: str,
        prompt_version: str,
    ) -> AdapterResult:
        if not self.is_available:
            return AdapterResult(
                success=False,
                error="Gemini not configured — no API key or SDK unavailable",
            )

        start = time.monotonic()

        try:
            from app.services.intent_engine.prompts import get_prompt

            prompt_template = get_prompt(prompt_version)
            prompt = prompt_template.format(
                canonical_request=canonical_request,
                resolved_currency=resolved_currency or "unknown",
                transaction_type_hint=transaction_type_hint or "none",
                reference_timestamp=reference_timestamp,
                schema_json="See StructuredIntent schema",
            )

            response = self._client.models.generate_content(  # type: ignore[union-attr]
                model=self._model_name,
                contents=prompt,
                config=genai_types.GenerateContentConfig(  # type: ignore[union-attr]
                    max_output_tokens=self._max_output_tokens,
                    temperature=0.1,
                    response_mime_type="application/json",
                ),
            )

            latency = int((time.monotonic() - start) * 1000)

            raw_text = response.text
            raw_output = json.loads(raw_text)

            tokens_used = 0
            if response.usage_metadata:
                tokens_used = getattr(
                    response.usage_metadata, "total_token_count", 0
                )

            return AdapterResult(
                success=True,
                raw_output=raw_output,
                provider_info=ProviderInfo(
                    provider="gemini",
                    model=self._model_name,
                    latency_ms=latency,
                    tokens_used=tokens_used,
                ),
            )

        except Exception as e:
            return AdapterResult(
                success=False,
                error=f"Gemini error: {e}",
            )

    async def health_check(self) -> bool:
        return self.is_available

    def get_provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            provider="gemini",
            model=self._model_name,
        )
