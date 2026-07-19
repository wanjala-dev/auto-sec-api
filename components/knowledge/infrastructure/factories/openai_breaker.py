"""Thin circuit-breaker wrappers for OpenAI chat + embeddings calls.

OpenAI is reached through the langchain factories (``llms/chatopenai.py``
and ``embeddings/openai.py``). When OpenAI is down or rate-limiting, a
fleet of Celery embedding/agent tasks will each retry, amplifying the
storm (celery-tasks skill §3e). These helpers gate the *call site* so a
single down-provider fails fast across the process instead of every task
exhausting its own retry budget against a dead endpoint.

Construction is cheap and side-effect-free, so we deliberately do NOT
gate factory construction — we gate the actual network call. Two slugs
keep chat and embeddings health independent in the shared registry.
"""
from __future__ import annotations

import logging

from components.shared_kernel.domain.circuit_breaker import circuit_breaker_registry

logger = logging.getLogger(__name__)

OPENAI_CHAT_SLUG = "openai_chat"
OPENAI_EMBEDDINGS_SLUG = "openai_embeddings"


class OpenAIUnavailableError(RuntimeError):
    """Raised when the OpenAI circuit breaker is OPEN for a given slug.

    Carries the slug so callers / Celery retry logic can decide whether to
    back off rather than hammer a provider the breaker already knows is down.
    """

    def __init__(self, slug: str):
        self.slug = slug
        super().__init__(
            f"OpenAI circuit breaker open for slug={slug}; refusing request to a "
            "provider recently observed as failing"
        )


def openai_allow_request(slug: str) -> bool:
    """Return True if the breaker for ``slug`` will accept a new request."""
    return circuit_breaker_registry.get(slug).allow_request()


def record_openai_success(slug: str) -> None:
    circuit_breaker_registry.get(slug).record_success()


def record_openai_failure(slug: str) -> None:
    circuit_breaker_registry.get(slug).record_failure()
