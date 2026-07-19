"""CachingToolAccessAdapter — decorator that wraps any ToolAccessPort
adapter with transparent caching.

This is an infrastructure adapter that implements the Decorator pattern:
it satisfies the ``ToolAccessPort`` interface and delegates to a wrapped
adapter, caching results for deterministic operations.

The ``ToolExecutionPolicy`` decides whether a call is cacheable; this
adapter honours that decision.

Plugged in at the composition root (``AIProvider``) via::

    caching = CachingToolAccessAdapter(inner=OrmToolAccessAdapter(), ttl=300)
    resolver.register(ToolAccessStrategy.ORM, caching)
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from components.agents.application.ports.tool_access_port import ToolAccessPort

logger = logging.getLogger(__name__)


@dataclass
class _CacheEntry:
    """Internal: a cached result with expiry metadata."""

    result: Any
    created_at: float          # time.monotonic()
    ttl_seconds: int
    hit_count: int = 0

    @property
    def is_expired(self) -> bool:
        return (time.monotonic() - self.created_at) > self.ttl_seconds


class CachingToolAccessAdapter(ToolAccessPort):
    """Decorator adapter that caches results from an inner ToolAccessPort.

    - Only caches successful results (no exceptions).
    - Uses a SHA-256 key derived from (operation, workspace_id, params, access_config).
    - Evicts expired entries lazily (on access) and eagerly via ``evict_expired()``.
    - Thread-safe for single-process Django (GIL); for multi-process
      deployments, swap the in-memory dict for Redis/memcached.
    """

    def __init__(
        self,
        inner: ToolAccessPort,
        ttl: int = 300,
        max_entries: int = 1_000,
    ) -> None:
        self._inner = inner
        self._default_ttl = ttl
        self._max_entries = max_entries
        self._cache: Dict[str, _CacheEntry] = {}

    # ── ToolAccessPort interface ─────────────────────────────────────

    def execute(
        self,
        *,
        operation: str,
        workspace_id: str,
        params: Dict[str, Any],
        access_config: Dict[str, Any],
    ) -> Any:
        cache_key = self._build_key(
            operation=operation,
            workspace_id=workspace_id,
            params=params,
            access_config=access_config,
        )

        # Check cache
        entry = self._cache.get(cache_key)
        if entry is not None and not entry.is_expired:
            entry.hit_count += 1
            logger.debug(
                "Cache HIT for %s (hits=%d)", cache_key[:16], entry.hit_count,
            )
            return entry.result

        # Cache miss or expired — delegate to inner adapter
        if entry is not None:
            del self._cache[cache_key]

        result = self._inner.execute(
            operation=operation,
            workspace_id=workspace_id,
            params=params,
            access_config=access_config,
        )

        # Store in cache
        self._store(cache_key, result)
        return result

    def supports_operation(self, operation: str) -> bool:
        return self._inner.supports_operation(operation)

    def list_operations(self) -> List[str]:
        return self._inner.list_operations()

    def health_check(self, access_config: Dict[str, Any]) -> bool:
        return self._inner.health_check(access_config)

    # ── Batch support (delegate to inner) ────────────────────────────

    def execute_batch(
        self,
        *,
        workspace_id: str,
        items: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Batch execution with per-item caching.

        Items that are cached get served from cache; remaining items
        are forwarded as a batch to the inner adapter.
        """
        results: List[Dict[str, Any]] = [{}] * len(items)
        uncached_indices: List[int] = []
        uncached_items: List[Dict[str, Any]] = []

        for i, item in enumerate(items):
            cache_key = self._build_key(
                operation=item.get("operation", ""),
                workspace_id=workspace_id,
                params=item.get("params", {}),
                access_config=item.get("access_config", {}),
            )
            entry = self._cache.get(cache_key)
            if entry is not None and not entry.is_expired:
                entry.hit_count += 1
                results[i] = {
                    "success": True,
                    "result": entry.result,
                    "cache_hit": True,
                }
            else:
                uncached_indices.append(i)
                uncached_items.append(item)

        # Delegate uncached items to inner adapter
        if uncached_items and hasattr(self._inner, "execute_batch"):
            batch_results = self._inner.execute_batch(
                workspace_id=workspace_id,
                items=uncached_items,
            )
            for idx, batch_result in zip(uncached_indices, batch_results):
                results[idx] = batch_result
                # Cache successful results
                if batch_result.get("success"):
                    item = items[idx]
                    cache_key = self._build_key(
                        operation=item.get("operation", ""),
                        workspace_id=workspace_id,
                        params=item.get("params", {}),
                        access_config=item.get("access_config", {}),
                    )
                    self._store(cache_key, batch_result.get("result"))
        elif uncached_items:
            # Inner adapter doesn't support batch — fall back to sequential
            for idx, item in zip(uncached_indices, uncached_items):
                try:
                    result = self._inner.execute(
                        operation=item.get("operation", ""),
                        workspace_id=workspace_id,
                        params=item.get("params", {}),
                        access_config=item.get("access_config", {}),
                    )
                    results[idx] = {"success": True, "result": result}
                    cache_key = self._build_key(
                        operation=item.get("operation", ""),
                        workspace_id=workspace_id,
                        params=item.get("params", {}),
                        access_config=item.get("access_config", {}),
                    )
                    self._store(cache_key, result)
                except Exception as exc:
                    results[idx] = {"success": False, "error": str(exc)}

        return results

    # ── Cache management ─────────────────────────────────────────────

    def invalidate(self, cache_key: str) -> bool:
        """Remove a specific entry.  Returns True if it existed."""
        return self._cache.pop(cache_key, None) is not None

    def invalidate_all(self) -> int:
        """Clear the entire cache.  Returns number of entries removed."""
        count = len(self._cache)
        self._cache.clear()
        return count

    def evict_expired(self) -> int:
        """Remove all expired entries.  Returns number evicted."""
        expired = [k for k, v in self._cache.items() if v.is_expired]
        for k in expired:
            del self._cache[k]
        return len(expired)

    @property
    def cache_size(self) -> int:
        return len(self._cache)

    @property
    def active_cache_keys(self) -> frozenset:
        """Return cache keys that are still valid (for policy checks)."""
        return frozenset(
            k for k, v in self._cache.items() if not v.is_expired
        )

    # ── Internal helpers ─────────────────────────────────────────────

    def _store(self, cache_key: str, result: Any) -> None:
        """Store a result, evicting oldest if at capacity."""
        if len(self._cache) >= self._max_entries:
            self.evict_expired()
        if len(self._cache) >= self._max_entries:
            # Evict least-hit entry
            least_hit_key = min(
                self._cache, key=lambda k: self._cache[k].hit_count,
            )
            del self._cache[least_hit_key]

        self._cache[cache_key] = _CacheEntry(
            result=result,
            created_at=time.monotonic(),
            ttl_seconds=self._default_ttl,
        )

    @staticmethod
    def _build_key(
        *,
        operation: str,
        workspace_id: str,
        params: Dict[str, Any],
        access_config: Dict[str, Any],
    ) -> str:
        payload = json.dumps(
            {
                "op": operation,
                "ws": workspace_id,
                "params": params,
                "cfg": access_config,
            },
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(payload.encode()).hexdigest()
