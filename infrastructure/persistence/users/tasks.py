"""Celery task shim — delegates to canonical component module.

This file exists so that ``celery.autodiscover_tasks()`` (which scans
INSTALLED_APPS) can find and register the tasks defined in the
components layer.
"""
from components.identity.infrastructure.tasks.user_tasks import (  # noqa: F401
    notify_security_event,
)
