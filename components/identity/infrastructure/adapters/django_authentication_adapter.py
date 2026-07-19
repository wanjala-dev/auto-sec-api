"""Infrastructure adapter implementing AuthenticationPort.

Wraps Django's ``auth.authenticate`` behind the port contract,
keeping Django imports in the infrastructure layer.
"""

from __future__ import annotations

import secrets
from uuid import UUID

from components.identity.domain.entities.user_entity import UserEntity
from components.identity.mappers.db.user_mapper import to_user_entity
from components.identity.application.ports.authentication_port import AuthenticationPort


# Precomputed unmatchable hash, built once at import time using the current
# PASSWORD_HASHERS config. Used to burn the same CPU time as a real bcrypt
# compare when the email doesn't exist, preventing email-enumeration via
# response-time analysis.
_TIMING_ATTACK_HASH: str | None = None


def _get_timing_attack_hash() -> str:
    global _TIMING_ATTACK_HASH
    if _TIMING_ATTACK_HASH is None:
        from django.contrib.auth.hashers import make_password

        _TIMING_ATTACK_HASH = make_password(secrets.token_urlsafe(32))
    return _TIMING_ATTACK_HASH


class DjangoAuthenticationAdapter(AuthenticationPort):
    """Concrete adapter backed by Django's authentication backend."""

    def authenticate(self, email: str, password: str) -> UserEntity | None:
        from django.contrib.auth import authenticate as django_authenticate
        from django.contrib.auth.hashers import check_password

        user = django_authenticate(email=email, password=password)
        if user is None:
            check_password(password, _get_timing_attack_hash())
            return None
        return to_user_entity(user)

    def find_by_email(self, email: str) -> UserEntity | None:
        from infrastructure.persistence.users.models import CustomUser

        try:
            user = CustomUser.objects.get(email=email)
            return to_user_entity(user)
        except CustomUser.DoesNotExist:
            return None

    def get_auth_provider(self, email: str) -> str | None:
        from infrastructure.persistence.users.models import CustomUser

        provider = (
            CustomUser.objects.filter(email=email)
            .values_list("auth_provider", flat=True)
            .first()
        )
        return provider
