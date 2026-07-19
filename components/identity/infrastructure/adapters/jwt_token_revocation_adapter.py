"""JWT token revocation adapter using simplejwt blacklist."""

from __future__ import annotations

from typing import Any

from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from components.identity.application.ports.token_revocation_port import TokenRevocationPort


class JWTTokenRevocationAdapter(TokenRevocationPort):
    """Blacklists outstanding JWT tokens via the simplejwt token blacklist models."""

    def revoke_all_tokens(self, *, user_id: Any) -> int:
        outstanding = OutstandingToken.objects.filter(user_id=user_id)
        count = 0
        for token in outstanding:
            _, created = BlacklistedToken.objects.get_or_create(token=token)
            if created:
                count += 1
        return count

    def revoke_token(self, *, token_string: str) -> bool:
        try:
            token = OutstandingToken.objects.get(token=token_string)
        except OutstandingToken.DoesNotExist:
            return False
        _, created = BlacklistedToken.objects.get_or_create(token=token)
        return created

    def revoke_by_jti(self, *, jti: str) -> bool:
        try:
            token = OutstandingToken.objects.get(jti=jti)
        except OutstandingToken.DoesNotExist:
            return False
        _, created = BlacklistedToken.objects.get_or_create(token=token)
        return created
