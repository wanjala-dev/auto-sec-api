"""Cache-backed adapter implementing AuthLockoutPort.

Uses Django cache (Redis/Memcached in production) for lockout state.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from components.identity.application.ports.auth_lockout_port import AuthLockoutPort


class CacheLockoutAdapter(AuthLockoutPort):
    """Concrete adapter backed by Django cache."""

    def _key(self, scope: str, identifier: str) -> str:
        return f"auth:lockout:{scope}:{identifier}"

    def _get_payload(self, scope: str, identifier: str) -> dict:
        return cache.get(self._key(scope, identifier)) or {"count": 0, "locked_until": None}

    def get_failure_count(self, scope: str, identifier: str) -> int:
        payload = self._get_payload(scope, identifier)
        return int(payload.get("count", 0))

    def is_locked(self, scope: str, identifier: str) -> tuple[bool, int]:
        payload = self._get_payload(scope, identifier)
        locked_until = payload.get("locked_until")
        if locked_until and timezone.now() < locked_until:
            remaining = int((locked_until - timezone.now()).total_seconds())
            return True, max(remaining, 1)
        return False, 0

    def increment_failure(self, scope: str, identifier: str) -> int:
        key = self._key(scope, identifier)
        payload = self._get_payload(scope, identifier)
        payload["count"] = int(payload.get("count", 0)) + 1
        # Keep the entry alive for the lockout window duration
        cache.set(key, payload, timeout=15 * 60)
        return payload["count"]

    def activate_lockout(self, scope: str, identifier: str, window_minutes: int) -> None:
        key = self._key(scope, identifier)
        payload = self._get_payload(scope, identifier)
        payload["locked_until"] = timezone.now() + timedelta(minutes=window_minutes)
        cache.set(key, payload, timeout=window_minutes * 60)

    def clear(self, scope: str, identifier: str) -> None:
        cache.delete(self._key(scope, identifier))
