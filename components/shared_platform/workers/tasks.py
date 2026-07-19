"""Beat-scheduled entry points for the shared_platform bounded context.

These are PRIMARY ADAPTERS — external triggers (Celery Beat scheduler)
that drive the application by calling into application services.

Activation
----------
These entry points are scaffolding for the target architecture.  To
activate them as the canonical Celery tasks:

1. Register ``components.shared_platform.workers`` in ``CELERY_IMPORTS`` or
   add it as an installed app in ``INSTALLED_APPS``.
2. Update ``CELERY_BEAT_SCHEDULE`` task references to the new names
   (prefixed ``workers.shared_platform.``).
3. Remove the ``@shared_task`` decorator from the corresponding
   functions in ``infrastructure/tasks/`` so they become plain
   callables.
"""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="shared_platform.cleanup_expired_demo_accounts")
def cleanup_expired_demo_accounts() -> dict:
    """Beat entry point — tear down every ACTIVE demo account whose TTL has expired.

    Thin primary adapter: delegates to the shared
    ``sweep_expired_demo_accounts`` service (the same code path the
    ``cleanup_demo_accounts`` management command uses) and returns its summary.

    Beat name: ``shared_platform.cleanup_expired_demo_accounts`` (daily 03:30 UTC).
    """
    from components.shared_platform.infrastructure.services.demo_account_teardown import (
        sweep_expired_demo_accounts,
    )

    logger.info("cleanup_expired_demo_accounts started")
    summary = sweep_expired_demo_accounts(apply=True)
    logger.info(
        "cleanup_expired_demo_accounts completed found=%s torn_down=%s users_deleted=%s stripe_deferred=%s errors=%s",
        summary["found"],
        summary["torn_down"],
        summary["users_deleted"],
        summary["stripe_deferred"],
        summary["errors"],
    )
    return summary
