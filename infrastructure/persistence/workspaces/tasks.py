"""Celery task shim — delegates to canonical component module.

This file exists so that ``celery.autodiscover_tasks()`` (which scans
INSTALLED_APPS) can find and register the tasks defined in the
components layer.
"""
from components.workspace.infrastructure.tasks.workspace_tasks import (  # noqa: F401
    expire_support_impersonation_sessions,
    prune_temporary_workspaces,
    sync_workspace_setup_banners,
)
