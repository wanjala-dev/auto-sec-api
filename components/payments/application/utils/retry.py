"""Synchronous retry with exponential backoff for gateway calls.

Used by use cases that need to call a provider gateway (Stripe, Braintree, etc.)
with automatic retry on transient failures. This is for synchronous request-time
calls, NOT Celery tasks (which have their own retry mechanism).

The retry is conservative:
- Only retries on transient errors (connection, timeout, 5xx)
- Uses exponential backoff with jitter to avoid thundering herds
- Defaults to 3 attempts with 1s base delay (1s → 2s → 4s)
- Raises the last exception if all attempts fail

Application-layer primitive — framework-free by design. Callers that
need framework-specific transient detection (Stripe / requests / httpx)
pass their own ``retryable`` predicate via
:func:`build_retryable_predicate` in their infrastructure adapter.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable, Iterable
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

_STDLIB_TRANSIENT: tuple[type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
)


def is_transient(exc: BaseException) -> bool:
    """Return True if the exception is a stdlib transient type.

    Infrastructure adapters that interact with Stripe / requests / httpx
    should call :func:`build_retryable_predicate` to add framework
    exception classes to this base predicate.
    """
    if isinstance(exc, _STDLIB_TRANSIENT):
        return True
    status = getattr(exc, "http_status", None)
    if isinstance(status, int) and status >= 500:
        return True
    return False


def build_retryable_predicate(
    extra_exceptions: Iterable[type[BaseException]] = (),
) -> Callable[[BaseException], bool]:
    """Compose the stdlib transient predicate with adapter-supplied types.

    Adapter usage::

        from stripe.error import APIConnectionError, RateLimitError
        retryable = build_retryable_predicate((APIConnectionError, RateLimitError))
        retry_with_backoff(self._gateway.charge, ..., retryable=retryable)
    """
    extras = tuple(extra_exceptions)

    def _predicate(exc: BaseException) -> bool:
        if isinstance(exc, extras):
            return True
        return is_transient(exc)

    return _predicate


def retry_with_backoff(
    fn: Callable[..., T],
    *args: Any,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter: bool = True,
    retryable: Callable[[BaseException], bool] = is_transient,
    on_retry: Callable[[BaseException, int, float], None] | None = None,
    **kwargs: Any,
) -> T:
    """Call ``fn(*args, **kwargs)`` with exponential backoff on transient failures."""
    last_exc: BaseException | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc

            if attempt >= max_attempts or not retryable(exc):
                raise

            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            if jitter:
                delay += random.uniform(0, delay * 0.5)

            if on_retry:
                on_retry(exc, attempt, delay)
            else:
                logger.warning(
                    "retry_with_backoff attempt=%d/%d delay=%.1fs error=%s",
                    attempt,
                    max_attempts,
                    delay,
                    exc,
                )

            time.sleep(delay)

    raise last_exc  # type: ignore[misc]
