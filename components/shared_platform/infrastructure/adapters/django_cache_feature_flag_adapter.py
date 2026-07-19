"""Django cache adapter implementing FeatureFlagCachePort."""

from __future__ import annotations

from typing import Optional

from components.shared_platform.application.ports.feature_flag_cache_port import FeatureFlagCachePort


FEATURE_FLAGS_VERSION_KEY = "feature_flags:v1:version"


class DjangoCacheFeatureFlagAdapter(FeatureFlagCachePort):
    """Concrete adapter backed by Django cache framework."""

    def get_version(self) -> int:
        from django.core.cache import cache

        version = cache.get(FEATURE_FLAGS_VERSION_KEY)
        if version is None:
            cache.add(FEATURE_FLAGS_VERSION_KEY, 1, timeout=None)
            return cache.get(FEATURE_FLAGS_VERSION_KEY) or 1
        return int(version)

    def bump_version(self) -> int:
        from django.core.cache import cache

        try:
            return int(cache.incr(FEATURE_FLAGS_VERSION_KEY))
        except ValueError:
            cache.set(FEATURE_FLAGS_VERSION_KEY, 1, timeout=None)
            return 1

    def get_evaluation(self, key: str) -> Optional[dict]:
        from django.core.cache import cache

        return cache.get(key)

    def set_evaluation(self, key: str, value: dict, timeout: int = 300) -> None:
        from django.core.cache import cache

        cache.set(key, value, timeout=timeout)
