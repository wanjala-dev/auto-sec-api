"""Beat-scheduled entry points for the workspace bounded context.

These are PRIMARY ADAPTERS — external triggers (Celery Beat scheduler)
that drive the application by calling into application services.

Activation
----------
These entry points are scaffolding for the target architecture.  To
activate them as the canonical Celery tasks:

1. Register ``components.workspace.workers`` in ``CELERY_IMPORTS`` or
   add it as an installed app in ``INSTALLED_APPS``.
2. Update ``CELERY_BEAT_SCHEDULE`` task references to the new names
   (prefixed ``workers.workspace.``).
3. Remove the ``@shared_task`` decorator from the corresponding
   functions in ``infrastructure/tasks/`` so they become plain
   callables.
"""

from __future__ import annotations

# === Workspace Setup Tasks (thin wrappers) ===


def sync_workspace_setup_banners():
    """Beat entry point — delegates to workspace setup synchronization service.

    Current Beat name: ``infrastructure.workspaces.tasks.sync_workspace_setup_banners``
    """
    from components.workspace.infrastructure.tasks.workspace_tasks import (
        sync_workspace_setup_banners as _impl,
    )

    return _impl()


def prune_temporary_workspaces(max_age_minutes=60):
    """Beat entry point — delegates to workspace cleanup service.

    Current Beat name: ``infrastructure.workspaces.tasks.prune_temporary_workspaces``
    """
    from components.workspace.infrastructure.tasks.workspace_tasks import (
        prune_temporary_workspaces as _impl,
    )

    return _impl(max_age_minutes)
