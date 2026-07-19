"""Application use case — consume a magic-link token + return a session.

Framework-free. Atomic consumption, user lookup/creation, and JWT
issuance happen behind the ``MagicLinkPort``; this use case is just
the orchestrator that maps the port's DTO into the controller's
response shape and a clean error result when the token is bad.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from components.identity.application.ports.magic_link_port import (
    MagicLinkPort,
)
from components.identity.application.ports.session_registry_port import SessionRegistryPort
from components.identity.domain.value_objects.auth_tokens import RequestContext


@dataclass(frozen=True)
class VerifyMagicLinkResult:
    user_id: str
    email: str
    username: str
    is_onboard_complete: bool
    is_contributor: bool
    tokens: dict
    next_url: str
    created_user: bool


@dataclass(frozen=True)
class VerifyMagicLinkError:
    code: str
    message: str
    status: int


_INVALID_OR_EXPIRED = VerifyMagicLinkError(
    code="invalid_token",
    message="This sign-in link is invalid or has expired.",
    status=400,
)


class VerifyMagicLinkUseCase:
    def __init__(
        self,
        *,
        magic_link: MagicLinkPort,
        session_registry: SessionRegistryPort,
    ):
        self._magic_link = magic_link
        self._sessions = session_registry

    def execute(
        self,
        *,
        token_value: str,
        context: RequestContext | None = None,
        request_ip: str | None = None,
    ):
        if not token_value:
            return _INVALID_OR_EXPIRED
        if request_ip is None and context is not None:
            request_ip = context.ip_address
        session = self._magic_link.consume_token(
            token_value=token_value,
            request_ip=request_ip,
        )
        if session is None:
            return _INVALID_OR_EXPIRED
        # Register the login session (never breaks sign-in — the adapter
        # logs + continues on failure).
        if session.refresh_jti and session.refresh_expires_at:
            self._sessions.create_session(
                user_id=UUID(str(session.user_id)),
                refresh_jti=session.refresh_jti,
                expires_at=session.refresh_expires_at,
                context=context,
                login_method="magic_link",
            )
        return VerifyMagicLinkResult(
            user_id=session.user_id,
            email=session.email,
            username=session.username,
            is_onboard_complete=session.is_onboard_complete,
            is_contributor=session.is_contributor,
            tokens={
                "access": session.access_token,
                "refresh": session.refresh_token,
            },
            next_url=session.next_url,
            created_user=session.created_user,
        )
