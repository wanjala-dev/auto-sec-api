"""Provider for broadcast ORM models.

This provider isolates controllers from direct ``infrastructure.persistence.broadcast``
imports per the Explicit Architecture rules. Models are lazy-imported inside
property bodies so the module is framework-free at top level.
"""
from __future__ import annotations

from typing import Protocol


class BroadcastModelsProviderProtocol(Protocol):
    """Protocol describing the broadcast models provider surface."""

    @property
    def Banner(self):  # noqa: D401, N802 - ORM class accessor
        ...

    @property
    def BroadCast_Email(self):  # noqa: D401, N802 - ORM class accessor
        ...


class BroadcastModelsProvider:
    """Lazy provider for broadcast ORM model classes.

    Every accessor imports the underlying Django model inside the property body
    so that this module stays free of any infrastructure imports at top level.
    """

    @property
    def Banner(self):  # noqa: N802 - ORM class accessor
        from infrastructure.persistence.broadcast.models import Banner

        return Banner

    @property
    def BroadCast_Email(self):  # noqa: N802 - ORM class accessor
        from infrastructure.persistence.broadcast.models import BroadCast_Email

        return BroadCast_Email


_default_provider: BroadcastModelsProvider | None = None


def get_broadcast_models_provider() -> BroadcastModelsProvider:
    """Return the process-wide default :class:`BroadcastModelsProvider`."""
    global _default_provider
    if _default_provider is None:
        _default_provider = BroadcastModelsProvider()
    return _default_provider
