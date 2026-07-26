"""Published seam for knowledge's OpenAI circuit breaker.

The circuit breaker (request gating + success/failure recording around the
OpenAI backend) lives in knowledge infrastructure. Other contexts that guard
their OpenAI calls with it (the agents context's Celery tasks) reach it through
this application-layer re-export instead of importing
``knowledge.infrastructure.factories.openai_breaker`` directly — cross-context
infrastructure imports are forbidden (ADR 0004 infra-boundary series).

This module IS the composition seam: it re-publishes the breaker's public
surface (the request-gating functions, the unavailable error, and the channel
slugs) as knowledge's application-layer API.
"""

from __future__ import annotations

from components.knowledge.infrastructure.factories.openai_breaker import (
    OPENAI_CHAT_SLUG,
    OPENAI_EMBEDDINGS_SLUG,
    OpenAIUnavailableError,
    openai_allow_request,
    record_openai_failure,
    record_openai_success,
)

__all__ = [
    "OPENAI_CHAT_SLUG",
    "OPENAI_EMBEDDINGS_SLUG",
    "OpenAIUnavailableError",
    "openai_allow_request",
    "record_openai_failure",
    "record_openai_success",
]
