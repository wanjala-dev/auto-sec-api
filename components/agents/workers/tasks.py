"""Beat-scheduled entry points for the agents bounded context.

These are PRIMARY ADAPTERS — external triggers (Celery Beat scheduler)
that drive the application by calling into application services.

Activation
----------
These entry points are scaffolding for the target architecture.  To
activate them as the canonical Celery tasks:

1. Register ``components.agents.workers`` in ``CELERY_IMPORTS`` or
   add it as an installed app in ``INSTALLED_APPS``.
2. Update ``CELERY_BEAT_SCHEDULE`` task references to the new names
   (prefixed ``workers.agents.``).
3. Remove the ``@shared_task`` decorator from the corresponding
   functions in ``infrastructure/tasks/`` so they become plain
   callables.
"""
from __future__ import annotations


def schedule_ai_teammate_runs():
    """Beat entry point — schedules AI teammate execution for enabled workspaces.

    Current Beat name: ``ai.agents.tasks.schedule_ai_teammate_runs``
    """
    from components.agents.infrastructure.tasks.agent_tasks import (
        schedule_ai_teammate_runs as _impl,
    )
    return _impl()
