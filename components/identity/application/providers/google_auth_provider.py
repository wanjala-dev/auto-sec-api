"""Provider for the Google sign-in adapters.

Wraps ``GoogleIdTokenVerifier`` (token verification) and
``OrmGoogleAuthAdapter`` (user lookup/creation + JWT issuance) so
controllers / use cases never import the concrete adapters directly.

``verifier`` and ``store`` each return a *factory callable* that
yields a fresh adapter instance, mirroring the magic-link provider's
call-site ergonomics: ``Verifier = provider.verifier; v = Verifier()``.
"""
from __future__ import annotations

from typing import Any, Callable


def _verifier_factory() -> Any:
    from components.identity.infrastructure.adapters.google_token_verifier import (
        GoogleIdTokenVerifier,
    )
    return GoogleIdTokenVerifier()


def _store_factory() -> Any:
    from components.identity.infrastructure.adapters.orm_google_auth_adapter import (
        OrmGoogleAuthAdapter,
    )
    return OrmGoogleAuthAdapter()


class GoogleAuthProvider:
    """Façade over identity infrastructure Google-auth adapters."""

    @property
    def verifier(self) -> Callable[[], Any]:
        return _verifier_factory

    @property
    def store(self) -> Callable[[], Any]:
        return _store_factory


_default = GoogleAuthProvider()


def get_google_auth_provider() -> GoogleAuthProvider:
    return _default
