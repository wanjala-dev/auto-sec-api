"""Provider for magic-link email + ORM operations.

Wraps ``django_magic_link_email_adapter`` (sender) and
``orm_magic_link_adapter`` (store) so the controllers / use cases
never import the concrete adapters directly.

``email_sender`` and ``store`` each return a *factory callable* that
yields a fresh adapter instance, mirroring the original
``DjangoMagicLinkEmailAdapter()`` / ``OrmMagicLinkAdapter()`` call
sites — controllers can just do ``Sender = provider.email_sender;
sender_instance = Sender()``.
"""

from __future__ import annotations

from typing import Any, Callable


def _email_sender_factory() -> Any:
    from components.identity.infrastructure.adapters.django_magic_link_email_adapter import (
        DjangoMagicLinkEmailAdapter,
    )
    return DjangoMagicLinkEmailAdapter()


def _store_factory() -> Any:
    from components.identity.infrastructure.adapters.orm_magic_link_adapter import (
        OrmMagicLinkAdapter,
    )
    return OrmMagicLinkAdapter()


class MagicLinkProvider:
    """Façade over identity infrastructure magic-link adapters."""

    @property
    def email_sender(self) -> Callable[[], Any]:
        return _email_sender_factory

    @property
    def store(self) -> Callable[[], Any]:
        return _store_factory


_default = MagicLinkProvider()


def get_magic_link_provider() -> MagicLinkProvider:
    return _default
