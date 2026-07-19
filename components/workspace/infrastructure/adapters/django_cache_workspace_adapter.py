"""Django cache adapter implementing WorkspaceCachePort."""

from __future__ import annotations

from typing import Any, Optional

from components.workspace.application.ports.workspace_cache_port import WorkspaceCachePort


class DjangoCacheWorkspaceAdapter(WorkspaceCachePort):
    """Concrete adapter backed by Django cache framework."""

    def get(self, key: str) -> Optional[Any]:
        from django.core.cache import cache

        return cache.get(key)

    def set(self, key: str, value: Any, timeout: int = 300) -> None:
        from django.core.cache import cache

        cache.set(key, value, timeout=timeout)

    def delete(self, key: str) -> None:
        from django.core.cache import cache

        cache.delete(key)
