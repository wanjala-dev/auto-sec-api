"""In-memory circuit breaker for external-provider health tracking.

Lives in the shared kernel because it is a generic resilience primitive,
not a payments concern — Stripe, Plaid, OpenAI embeddings/chat, and SES
all reach down-able external dependencies and all want the same
fail-fast-when-down behaviour (celery-tasks skill §3e). Keying by slug
keeps each provider's health independent in the shared registry.

Each provider slug gets its own ``ProviderCircuitBreaker`` instance which
tracks recent successes and failures in a sliding time window.  The
breaker transitions through three states:

    CLOSED   – provider is healthy, requests flow normally.
    OPEN     – failure threshold exceeded, requests are rejected
               until ``recovery_timeout`` elapses.
    HALF_OPEN – after recovery timeout, a limited number of probe
                requests are allowed through. If they succeed the
                breaker resets to CLOSED; if they fail it re-opens.

The ``CircuitBreakerRegistry`` is the single entry-point for the rest of
the application.  It is deliberately **in-memory** (no database or
cache backend) because:

* Provider health is inherently per-process — one web worker might
  have network issues while another is fine.
* A Redis/DB backend would add latency on every external call.
* On restart the breaker starts CLOSED, which is the safe default.

Thread-safety is achieved with a per-breaker ``threading.Lock``.
"""

from __future__ import annotations

import enum
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import NamedTuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------

class CircuitState(enum.Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class HealthSnapshot(NamedTuple):
    """Point-in-time view of a provider's health."""

    slug: str
    state: CircuitState
    failure_count: int
    success_count: int
    failure_rate: float  # 0.0 – 1.0
    last_failure_time: float | None  # epoch seconds


@dataclass
class CircuitBreakerConfig:
    """Tuning knobs – sensible defaults for payment providers."""

    failure_threshold: int = 5
    """Number of failures in the window before opening the circuit."""

    success_threshold: int = 2
    """Consecutive successes in HALF_OPEN required to close the circuit."""

    recovery_timeout: float = 60.0
    """Seconds to wait in OPEN before transitioning to HALF_OPEN."""

    window_size: float = 120.0
    """Sliding window (seconds) over which failures are counted."""

    half_open_max_calls: int = 3
    """Max concurrent probe calls allowed in HALF_OPEN state."""


# ---------------------------------------------------------------------------
# Per-provider breaker
# ---------------------------------------------------------------------------

@dataclass
class _Outcome:
    timestamp: float
    success: bool


class ProviderCircuitBreaker:
    """Circuit breaker for a single payment provider."""

    def __init__(self, slug: str, config: CircuitBreakerConfig | None = None):
        self.slug = slug
        self.config = config or CircuitBreakerConfig()
        self._lock = threading.Lock()
        self._state = CircuitState.CLOSED
        self._outcomes: deque[_Outcome] = deque()
        self._last_failure_time: float | None = None
        self._opened_at: float | None = None
        self._half_open_calls: int = 0
        self._half_open_successes: int = 0

    # -- public interface ---------------------------------------------------

    @property
    def state(self) -> CircuitState:
        with self._lock:
            self._maybe_transition()
            return self._state

    def allow_request(self) -> bool:
        """Return True if this provider should accept a new request."""
        with self._lock:
            self._maybe_transition()
            if self._state is CircuitState.CLOSED:
                return True
            if self._state is CircuitState.HALF_OPEN:
                if self._half_open_calls < self.config.half_open_max_calls:
                    self._half_open_calls += 1
                    return True
                return False
            # OPEN
            return False

    def record_success(self) -> None:
        now = time.monotonic()
        with self._lock:
            self._outcomes.append(_Outcome(now, True))
            self._prune(now)
            if self._state is CircuitState.HALF_OPEN:
                self._half_open_successes += 1
                if self._half_open_successes >= self.config.success_threshold:
                    self._transition_to(CircuitState.CLOSED)
            logger.debug("circuit_breaker.success slug=%s state=%s", self.slug, self._state.value)

    def record_failure(self) -> None:
        now = time.monotonic()
        with self._lock:
            self._outcomes.append(_Outcome(now, False))
            self._last_failure_time = now
            self._prune(now)
            if self._state is CircuitState.HALF_OPEN:
                self._transition_to(CircuitState.OPEN)
            elif self._state is CircuitState.CLOSED:
                failures = sum(1 for o in self._outcomes if not o.success)
                if failures >= self.config.failure_threshold:
                    self._transition_to(CircuitState.OPEN)
            logger.debug("circuit_breaker.failure slug=%s state=%s", self.slug, self._state.value)

    def health_snapshot(self) -> HealthSnapshot:
        with self._lock:
            now = time.monotonic()
            self._prune(now)
            self._maybe_transition()
            total = len(self._outcomes)
            failures = sum(1 for o in self._outcomes if not o.success)
            successes = total - failures
            rate = failures / total if total else 0.0
            return HealthSnapshot(
                slug=self.slug,
                state=self._state,
                failure_count=failures,
                success_count=successes,
                failure_rate=rate,
                last_failure_time=self._last_failure_time,
            )

    def reset(self) -> None:
        """Force the breaker back to CLOSED (e.g. after manual recovery)."""
        with self._lock:
            self._transition_to(CircuitState.CLOSED)

    # -- internal -----------------------------------------------------------

    def _maybe_transition(self) -> None:
        """Check time-based transitions (must be called under lock)."""
        if self._state is CircuitState.OPEN and self._opened_at is not None:
            elapsed = time.monotonic() - self._opened_at
            if elapsed >= self.config.recovery_timeout:
                self._transition_to(CircuitState.HALF_OPEN)

    def _transition_to(self, new_state: CircuitState) -> None:
        old = self._state
        self._state = new_state
        if new_state is CircuitState.OPEN:
            self._opened_at = time.monotonic()
            self._half_open_calls = 0
            self._half_open_successes = 0
        elif new_state is CircuitState.HALF_OPEN:
            self._half_open_calls = 0
            self._half_open_successes = 0
        elif new_state is CircuitState.CLOSED:
            self._outcomes.clear()
            self._opened_at = None
            self._half_open_calls = 0
            self._half_open_successes = 0
        if old is not new_state:
            logger.info(
                "circuit_breaker.transition slug=%s %s -> %s",
                self.slug,
                old.value,
                new_state.value,
            )

    def _prune(self, now: float) -> None:
        cutoff = now - self.config.window_size
        while self._outcomes and self._outcomes[0].timestamp < cutoff:
            self._outcomes.popleft()


# ---------------------------------------------------------------------------
# Global registry
# ---------------------------------------------------------------------------

class CircuitBreakerRegistry:
    """Process-global registry of per-provider circuit breakers.

    Usage::

        from components.shared_kernel.domain.circuit_breaker import circuit_breaker_registry

        breaker = circuit_breaker_registry.get("stripe")
        if not breaker.allow_request():
            raise ProviderUnavailableError("stripe")
        try:
            result = stripe_gateway.create_checkout_session(...)
            breaker.record_success()
        except Exception:
            breaker.record_failure()
            raise
    """

    def __init__(self, default_config: CircuitBreakerConfig | None = None):
        self._default_config = default_config or CircuitBreakerConfig()
        self._breakers: dict[str, ProviderCircuitBreaker] = {}
        self._lock = threading.Lock()

    def get(self, slug: str) -> ProviderCircuitBreaker:
        slug_lower = slug.lower()
        with self._lock:
            if slug_lower not in self._breakers:
                self._breakers[slug_lower] = ProviderCircuitBreaker(
                    slug_lower, self._default_config,
                )
            return self._breakers[slug_lower]

    def configure(self, slug: str, config: CircuitBreakerConfig) -> None:
        """Override config for a specific provider."""
        slug_lower = slug.lower()
        with self._lock:
            self._breakers[slug_lower] = ProviderCircuitBreaker(slug_lower, config)

    def all_snapshots(self) -> list[HealthSnapshot]:
        with self._lock:
            slugs = list(self._breakers.keys())
        return [self._breakers[s].health_snapshot() for s in slugs]

    def reset_all(self) -> None:
        """Reset every breaker to CLOSED (useful in tests)."""
        with self._lock:
            for breaker in self._breakers.values():
                breaker.reset()


# Module-level singleton – import this everywhere.
circuit_breaker_registry = CircuitBreakerRegistry()
