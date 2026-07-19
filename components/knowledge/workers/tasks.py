"""Beat-scheduled entry points for the knowledge bounded context.

These are PRIMARY ADAPTERS — external triggers (Celery Beat scheduler)
that drive the application by calling into application services.

Activation
----------
These entry points are scaffolding for the target architecture.  To
activate them as the canonical Celery tasks:

1. Register ``components.knowledge.workers`` in ``CELERY_IMPORTS`` or
   add it as an installed app in ``INSTALLED_APPS``.
2. Update ``CELERY_BEAT_SCHEDULE`` task references to the new names
   (prefixed ``workers.knowledge.``).
3. Remove the ``@shared_task`` decorator from the corresponding
   functions in ``infrastructure/tasks/`` so they become plain
   callables.
"""
from __future__ import annotations


def create_embeddings_for_workspace_content():
    """Beat entry point — creates embeddings for workspace content updated in last 24h.

    Current Beat name: ``ai.embeddings.tasks.create_embeddings_for_workspace_content``

    TODO: Extract business logic into application/use_cases/ and call
    the use case directly from here.
    """
    from components.knowledge.infrastructure.tasks.embedding_tasks import (
        create_embeddings_for_workspace_content as _impl,
    )
    return _impl()
