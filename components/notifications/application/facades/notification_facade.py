"""Application-layer facade exposing notification services to other bounded contexts.

Per Explicit Architecture rule 7, other contexts must not import directly
from our infrastructure layer. This facade provides the approved cross-context interface.
"""
from components.notifications.infrastructure.adapters.notification_service import (
    NotificationDispatcher,
)

__all__ = ["NotificationDispatcher"]
