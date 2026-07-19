"""Use case: Record an authentication failure and potentially activate lockout.

No Django imports — depends only on ports and domain policies.
"""

from __future__ import annotations

from components.identity.domain.policies.auth_lockout_policy import (
    LockoutStatus,
    evaluate_lockout,
    lockout_window_minutes,
    should_lock,
)
from components.identity.application.ports.auth_lockout_port import AuthLockoutPort


class RecordAuthFailureUseCase:
    """Application use case for recording auth failures."""

    def __init__(self, lockout_port: AuthLockoutPort) -> None:
        self._lockout_port = lockout_port

    def execute(self, scope: str, identifier: str) -> LockoutStatus:
        new_count = self._lockout_port.increment_failure(scope, identifier)

        if should_lock(new_count):
            self._lockout_port.activate_lockout(scope, identifier, lockout_window_minutes())

        is_locked, remaining_seconds = self._lockout_port.is_locked(scope, identifier)
        return evaluate_lockout(new_count, is_locked, remaining_seconds)
