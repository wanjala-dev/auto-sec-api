"""Signal bridge: invalidate feature flag cache on FeatureFlag/FeatureFlagRule changes.

Extracted from apps/core/signals.py — keeps the cache-invalidation side effect
registered through the component infrastructure layer.

Registration happens in apps/core/apps.py:ready().
"""
from __future__ import annotations

import logging

from django.db.models.signals import post_delete, post_save

logger = logging.getLogger(__name__)


class DjangoFeatureFlagSignalBridge:
    """Registers post_save/post_delete on FeatureFlag and FeatureFlagRule to bump the cache version."""

    @staticmethod
    def register() -> None:
        from infrastructure.persistence.core.models import FeatureFlag, FeatureFlagRule

        signal_map = [
            (post_save, FeatureFlag, "shared_platform:feature_flag_post_save_FeatureFlag"),
            (post_delete, FeatureFlag, "shared_platform:feature_flag_post_delete_FeatureFlag"),
            (post_save, FeatureFlagRule, "shared_platform:feature_flag_post_save_FeatureFlagRule"),
            (post_delete, FeatureFlagRule, "shared_platform:feature_flag_post_delete_FeatureFlagRule"),
        ]
        for signal, model, uid in signal_map:
            signal.connect(
                _invalidate_feature_flag_cache,
                sender=model,
                weak=False,
                dispatch_uid=uid,
            )


def _invalidate_feature_flag_cache(sender, instance, **kwargs):
    try:
        from components.shared_platform.infrastructure.services.feature_flags import bump_feature_flags_version

        bump_feature_flags_version()
    except Exception:
        logger.exception("Failed to invalidate feature flag cache for %s", sender.__name__)
