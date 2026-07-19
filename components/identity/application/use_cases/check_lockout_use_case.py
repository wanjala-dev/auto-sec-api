"""Use case: Check whether an identifier is locked out.

No Django imports — depends only on ports and domain policies.
"""

from __future__ import annotations

from components.identity.domain.policies.auth_lockout_policy import LockoutStatus, evaluate_lockout
from components.identity.application.ports.auth_lockout_port import AuthLockoutPort


class CheckLockoutUseCase:
    """Application use case for evaluating lockout status."""

    def __init__(self, lockout_port: AuthLockoutPort) -> None:
        self._lockout_port = lockout_port

    def execute(self, scope: str, identifier: str) -> LockoutStatus:
        failure_count = self._lockout_port.get_failure_count(scope, identifier)
        is_locked, remaining_seconds = self._lockout_port.is_locked(scope, identifier)
        return evaluate_lockout(failure_count, is_locked, remaining_seconds)
