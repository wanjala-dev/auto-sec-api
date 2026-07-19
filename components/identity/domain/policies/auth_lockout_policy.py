"""Domain policy for authentication lockout.

Pure business rules — no Django, no cache, no ORM.
Infrastructure adapters implement the actual storage.
"""

from __future__ import annotations

from dataclasses import dataclass

from components.identity.domain.enums import (
    LOCKOUT_THRESHOLD,
    LOCKOUT_WARN_AT,
    LOCKOUT_WINDOW_MINUTES,
)


@dataclass(frozen=True)
class LockoutStatus:
    """Value object representing current lockout state."""

    locked: bool
    remaining_seconds: int
    remaining_attempts: int
    warn: bool


def evaluate_lockout(failure_count: int, is_currently_locked: bool, remaining_seconds: int) -> LockoutStatus:
    """Evaluate lockout status given current failure state.

    This is a pure function — it doesn't read from cache or DB.
    The caller provides the current counts; this function applies the policy.
    """
    locked = is_currently_locked
    remaining_attempts = max(LOCKOUT_THRESHOLD - failure_count, 0)
    warn = failure_count >= LOCKOUT_WARN_AT and not locked

    return LockoutStatus(
        locked=locked,
        remaining_seconds=max(remaining_seconds, 0),
        remaining_attempts=remaining_attempts,
        warn=warn,
    )


def should_lock(failure_count: int) -> bool:
    """Return True if failure_count has reached the lockout threshold."""
    return failure_count >= LOCKOUT_THRESHOLD


def lockout_window_minutes() -> int:
    """Return the lockout window in minutes (domain constant)."""
    return LOCKOUT_WINDOW_MINUTES
