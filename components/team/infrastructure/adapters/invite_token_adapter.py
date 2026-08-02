"""Adapter: issue JWT tokens for an accepted invitee via simplejwt.

Implements :class:`InviteTokenPort`. Confines the ``rest_framework_simplejwt``
dependency to infrastructure so the accept use case stays framework-free.
"""

from __future__ import annotations

from components.team.application.ports.invite_token_port import (
    InviteTokenPort,
    IssuedTokens,
)


class SimpleJwtInviteTokenAdapter(InviteTokenPort):
    def issue_for_user(self, *, user_id: str) -> IssuedTokens:
        from rest_framework_simplejwt.tokens import RefreshToken

        from infrastructure.persistence.users.models import CustomUser

        user = CustomUser.objects.get(id=user_id)
        refresh = RefreshToken.for_user(user)
        return IssuedTokens(access=str(refresh.access_token), refresh=str(refresh))
