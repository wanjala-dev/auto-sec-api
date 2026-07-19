"""Port for a TTL'd key/value cache with atomic SETNX semantics.

The Tier 2 #7 reindex debounce and the Tier 3 #9 query-rewrite cache
both need:

* ``get(key) -> value | None`` — read a previously-set value.
* ``set(key, value, *, ttl_seconds)`` — write with expiry.
* ``add(key, value, *, ttl_seconds) -> bool`` — atomic
  set-if-not-exists.  ``True`` iff the key was newly set; the caller
  uses this as a Redis-SETNX-equivalent lock acquisition.

Production adapter wraps Django's cache framework (Redis in prod,
locmem in tests).  Unit tests use an in-memory fake that the test
constructs directly — application code never touches Django.

Keeps the Explicit Architecture rule honest: application use cases
do not import ``django.core.cache``.  Only the adapter does.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class KeyValueCachePort(ABC):
    """Abstract contract every key/value cache adapter must satisfy."""

    @abstractmethod
    def get(self, key: str) -> Optional[Any]:
        """Return the cached value for ``key`` or ``None`` if absent."""
        ...

    @abstractmethod
    def set(self, key: str, value: Any, *, ttl_seconds: int) -> None:
        """Unconditionally write ``value`` under ``key`` with TTL."""
        ...

    @abstractmethod
    def add(self, key: str, value: Any, *, ttl_seconds: int) -> bool:
        """Atomic set-if-absent.  Return ``True`` iff the write happened.

        Implementations must guarantee atomicity — concurrent callers
        must not both see ``True``.  Redis ``SETNX`` + Django
        ``cache.add`` give this for free; alternative backends should
        document any caveats.
        """
        ...
