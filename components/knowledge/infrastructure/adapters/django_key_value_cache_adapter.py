"""Django adapter for ``KeyValueCachePort``.

Wraps ``django.core.cache.cache`` so application code never imports
Django directly.  In production this is Redis; tests use the locmem
backend Django ships out-of-the-box.
"""
from __future__ import annotations

from typing import Any, Optional

from django.core.cache import cache

from components.knowledge.application.ports.key_value_cache_port import (
    KeyValueCachePort,
)


class DjangoKeyValueCacheAdapter(KeyValueCachePort):
    """Implements ``KeyValueCachePort`` via Django's cache framework."""

    def get(self, key: str) -> Optional[Any]:
        return cache.get(key)

    def set(self, key: str, value: Any, *, ttl_seconds: int) -> None:
        cache.set(key, value, timeout=ttl_seconds)

    def add(self, key: str, value: Any, *, ttl_seconds: int) -> bool:
        # ``cache.add`` returns True iff the key was newly set —
        # atomic SETNX equivalent on the configured backend (Redis
        # in prod, locmem in tests).
        return bool(cache.add(key, value, timeout=ttl_seconds))
