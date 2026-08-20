"""Adapter: sign a freshly-accepted invitee in, via ``identity``'s own surface.

Implements :class:`InviteTokenPort`. Sessions belong to ``identity``: it owns
token issuance, the ``sid`` claim, and the ``UserSession`` registry that
``SessionAwareJWTAuthentication`` checks on every request. So this delegates to
``identity``'s application layer rather than minting anything itself — the same
permitted cross-context shape ``IdentityInviteUserProvisioningAdapter`` already
uses for the user write (architecture-manifesto Rule 2 / architecture-skill C2).

It previously called ``RefreshToken.for_user(user)`` directly. That mints a
structurally valid pair with NO ``sid`` claim and NO session row, which made the
invitee's session invisible to ``/identity/me/sessions/`` and untouchable by
revoke-others, password change and password reset — an immortal session, in the
one context least equipped to notice.
"""

from __future__ import annotations

import logging

from components.team.application.ports.invite_token_port import (
    InviteTokenPort,
    IssuedTokens,
)

logger = logging.getLogger(__name__)


class SimpleJwtInviteTokenAdapter(InviteTokenPort):
    def issue_for_user(self, *, user_id: str) -> IssuedTokens:
        from uuid import UUID

        from components.identity.application.providers.identity_provider import (
            IdentityProvider,
        )

        resolved_id = UUID(str(user_id))
        token_pair = IdentityProvider.build_token_adapter().issue_tokens(
            resolved_id,
            otp_verified=False,
            device_id=None,
            include_refresh=True,
        )

        # Register the session so it is listable and revocable. Best-effort, in
        # line with SessionRegistryPort's contract that bookkeeping never breaks
        # a sign-in — but logged loudly, because a session that fails to
        # register will now (correctly) fail to authenticate.
        if token_pair.refresh_jti and token_pair.refresh_expires_at:
            try:
                IdentityProvider.build_session_registry().create_session(
                    user_id=resolved_id,
                    refresh_jti=token_pair.refresh_jti,
                    expires_at=token_pair.refresh_expires_at,
                    context=None,
                    login_method="invite",
                )
            except Exception:
                logger.exception("invite_session_registration_failed user_id=%s", user_id)

        return IssuedTokens(access=token_pair.access, refresh=token_pair.refresh or "")
