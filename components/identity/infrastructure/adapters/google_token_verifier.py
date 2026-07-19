"""Concrete ``GoogleTokenVerifierPort`` — verifies a Google ID token.

This is the ONLY module that talks to Google's verification libraries.
It is deliberately strict and fail-closed:

  * signature + expiry are checked by ``verify_oauth2_token`` against
    Google's rotating public certs;
  * the issuer must be exactly Google (no substring matching, so
    ``accounts.google.com.evil.com`` cannot slip through);
  * the audience must be one of OUR configured client IDs — a token
    minted for a different app is rejected even though its signature
    is valid. We check against a *set* so web / iOS / Android client
    IDs can all be accepted as the platform grows, without code
    changes (add them to ``GOOGLE_CLIENT_IDS``);
  * a small clock-skew tolerance absorbs minor client/server drift;
  * ANY verification failure is logged (reason kept server-side) and
    surfaced to the caller as ``None`` — never as an exception and
    never leaking config back to the client.
"""
from __future__ import annotations

import logging
import os
from typing import Iterable, Optional

from components.identity.application.ports.google_auth_port import (
    GoogleIdentity,
    GoogleTokenVerifierPort,
)

logger = logging.getLogger(__name__)

# Google may issue the ID token with either issuer form.
_VALID_ISSUERS = frozenset(
    {"accounts.google.com", "https://accounts.google.com"}
)

# Tolerate minor clock drift between Google, our server, and the client
# so a freshly-minted token isn't rejected as "used before issued".
_CLOCK_SKEW_SECONDS = 10


def _allowed_client_ids() -> frozenset[str]:
    """The set of audience values we accept.

    Sourced from the environment so ops can add mobile client IDs
    without a deploy of new code. ``GOOGLE_CLIENT_ID`` (the existing
    single web client) is always included; ``GOOGLE_CLIENT_IDS`` is an
    optional comma-separated list for additional platforms.
    """
    ids: set[str] = set()
    primary = (os.environ.get("GOOGLE_CLIENT_ID") or "").strip()
    if primary:
        ids.add(primary)
    extra = os.environ.get("GOOGLE_CLIENT_IDS") or ""
    for candidate in extra.split(","):
        candidate = candidate.strip()
        if candidate:
            ids.add(candidate)
    return frozenset(ids)


class GoogleIdTokenVerifier(GoogleTokenVerifierPort):
    """Production verifier backed by ``google-auth``."""

    def __init__(
        self,
        *,
        allowed_client_ids: Optional[Iterable[str]] = None,
        clock_skew_seconds: int = _CLOCK_SKEW_SECONDS,
    ) -> None:
        self._allowed = (
            frozenset(allowed_client_ids)
            if allowed_client_ids is not None
            else None
        )
        self._clock_skew = clock_skew_seconds

    def verify(self, raw_token: str) -> Optional[GoogleIdentity]:
        if not raw_token or not isinstance(raw_token, str):
            return None

        allowed = self._allowed if self._allowed is not None else _allowed_client_ids()
        if not allowed:
            # Misconfiguration: without a client ID we cannot verify the
            # audience, so we must refuse rather than trust blindly.
            logger.error(
                "google_verify_no_client_id_configured — "
                "set GOOGLE_CLIENT_ID (and optionally GOOGLE_CLIENT_IDS)"
            )
            return None

        try:
            # Import lazily so importing this module never drags in the
            # google libs at Django load time.
            from google.auth.transport import requests as google_requests
            from google.oauth2 import id_token as google_id_token

            # audience=None → the library verifies signature + expiry +
            # issuer but NOT audience; we do the audience check ourselves
            # against the allow-set below (the library only accepts a
            # single audience string, which can't express multiple
            # platform client IDs).
            claims = google_id_token.verify_oauth2_token(
                raw_token,
                google_requests.Request(),
                audience=None,
                clock_skew_in_seconds=self._clock_skew,
            )
        except ValueError as exc:
            # Bad signature, expired, malformed, wrong issuer — the
            # library raises ValueError for all untrusted-token cases.
            logger.info("google_verify_rejected reason=%s", exc)
            return None
        except Exception:  # pragma: no cover - defensive, network etc.
            logger.exception("google_verify_unexpected_error")
            return None

        issuer = claims.get("iss")
        if issuer not in _VALID_ISSUERS:
            logger.info("google_verify_bad_issuer iss=%s", issuer)
            return None

        audience = claims.get("aud")
        if audience not in allowed:
            # Token is genuine but was minted for a different app.
            logger.warning("google_verify_audience_mismatch aud=%s", audience)
            return None

        sub = claims.get("sub")
        email = (claims.get("email") or "").strip().lower()
        if not sub or not email:
            logger.info("google_verify_missing_sub_or_email")
            return None

        return GoogleIdentity(
            sub=str(sub),
            email=email,
            email_verified=bool(claims.get("email_verified", False)),
            name=(claims.get("name") or "").strip(),
            picture=(claims.get("picture") or "").strip(),
        )
