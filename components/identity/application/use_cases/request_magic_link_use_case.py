"""Application use case — mint a single-use sign-in token.

Framework-free per the identity bounded-context import rules. All
ORM + datetime + transaction handling lives behind the
``MagicLinkPort``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from components.identity.application.ports.magic_link_port import (
    MagicLinkPort,
)


DEFAULT_TTL_MINUTES = 15
MAX_NEXT_URL_LENGTH = 500


@dataclass(frozen=True)
class RequestMagicLinkResult:
    email: str
    token: str
    next_url: str


def _normalize_next_url(next_url: Optional[str]) -> str:
    """Validate the next-URL is a same-site relative path.

    Anything else opens an open-redirect: an attacker could request a
    magic link with ``next=https://evil.example/steal`` and the verify
    flow would happily 302 the freshly-authed user out of the demo
    into the attacker's site. So we strip anything that doesn't start
    with a single leading "/" and isn't an empty string.
    """
    if not next_url:
        return ""
    candidate = str(next_url).strip()
    if not candidate:
        return ""
    if len(candidate) > MAX_NEXT_URL_LENGTH:
        return ""
    if not candidate.startswith("/") or candidate.startswith("//"):
        return ""
    return candidate


class RequestMagicLinkUseCase:
    """Generate a magic-link token and return it for the controller
    to email out. Anti-enumeration is enforced at the controller
    layer (the response shape is identical regardless of result), so
    this use case has no special branching for missing-user cases.
    """

    def __init__(self, *, magic_link: MagicLinkPort):
        self._magic_link = magic_link

    def execute(
        self,
        *,
        email: str,
        next_url: Optional[str] = None,
        ttl_minutes: int = DEFAULT_TTL_MINUTES,
    ) -> Optional[RequestMagicLinkResult]:
        normalized_email = (email or "").strip().lower()
        if not normalized_email:
            return None
        safe_next = _normalize_next_url(next_url)
        minted = self._magic_link.mint_token(
            email=normalized_email,
            next_url=safe_next,
            ttl_minutes=ttl_minutes,
        )
        if minted is None:
            return None
        return RequestMagicLinkResult(
            email=minted.email,
            token=minted.token,
            next_url=minted.next_url,
        )
