"""Composition root for ``KeyValueCachePort``.

Lazy import of the Django adapter keeps the application layer free
of framework imports — the adapter only loads when a caller asks
the provider for an instance.
"""
from __future__ import annotations

from components.knowledge.application.ports.key_value_cache_port import (
    KeyValueCachePort,
)


def key_value_cache() -> KeyValueCachePort:
    """Return the configured cache adapter (Django/Redis in prod)."""
    from components.knowledge.infrastructure.adapters.django_key_value_cache_adapter import (
        DjangoKeyValueCacheAdapter,
    )

    return DjangoKeyValueCacheAdapter()
