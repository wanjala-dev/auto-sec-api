"""Helpers for caching notification aggregates.

These functions delegate to :class:`DjangoCacheNotificationAdapter`
so the cache backend can be swapped without touching callers.
"""
from __future__ import annotations

from django.apps import apps
from django.conf import settings

from components.notifications.infrastructure.adapters.django_cache_notification_adapter import (
    DjangoCacheNotificationAdapter,
)

CACHE_TIMEOUT = getattr(settings, 'NOTIFICATION_COUNT_CACHE_TIMEOUT', 60)

_adapter = DjangoCacheNotificationAdapter(timeout=CACHE_TIMEOUT)


def _notification_model():
    return apps.get_model('core_notifications', 'Notification')


def get_unread_count(user, workspace_id=None) -> int:
    """Return cached unread notification count for ``user`` (optionally scoped to a workspace)."""
    if user is None or not getattr(user, 'is_authenticated', False):
        return 0

    cached_value = _adapter.get_unread_count(user.id, workspace_id)
    if cached_value is not None:
        return cached_value

    Notification = _notification_model()
    filters = {'recipient': user, 'is_read': False}
    if workspace_id is not None:
        filters['workspace_id'] = workspace_id
    count = Notification.objects.filter(**filters).count()
    _adapter.set_unread_count(user.id, count, workspace_id)
    return count


def invalidate_unread_count_cache(user_id: int | None, workspace_id=None):
    if not user_id:
        return
    _adapter.invalidate(user_id, workspace_id)
