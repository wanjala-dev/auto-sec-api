"""Celery entry points for the identity bounded context.

Tasks are PRIMARY ADAPTERS — an external trigger (broker delivery or the
Beat scheduler) driving the application, just like an HTTP request. Each
task is a thin wrapper that delegates to a use case built by
``IdentityProvider``; ORM imports stay lazy (inside functions) so this
module is safe to import from ``api/celery.py`` before the app registry
is ready.

Tasks here:

* ``identity.enrich_user_session`` — parse a freshly-created session's
  User-Agent + IP into structured device/geo columns. Dispatched from
  ``OrmUserSessionRepository._after_create`` (post-commit, best-effort).
  Idempotent: re-running overwrites the parsed fields.
* ``identity.sweep_user_sessions`` — daily reconciliation + retention:
  mark expired-but-unrevoked sessions revoked ("expired_sweep"), prune
  sessions dead for > ``SESSION_RETENTION_DAYS``, prune auth audit events
  older than ``AUTH_AUDIT_RETENTION_DAYS``. Registered in
  ``CELERY_BEAT_SCHEDULE`` (api/settings/{local,dev,prod}.py).
"""

from __future__ import annotations

import logging
from datetime import timedelta
from uuid import UUID

from celery import shared_task

logger = logging.getLogger(__name__)

# How many audit rows to delete per DELETE statement — bounds the pk list
# Django materialises for cascade handling on very large backlogs.
_PRUNE_BATCH_SIZE = 5000


@shared_task(
    name="identity.enrich_user_session",
    bind=True,
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    soft_time_limit=60,
    time_limit=90,
)
def enrich_user_session(self, session_id: str) -> str:
    """Enrich one UserSession row with parsed device + geo facts."""
    from components.identity.application.providers.identity_provider import IdentityProvider

    logger.info(
        "identity.enrich_user_session started session_id=%s task_id=%s",
        session_id,
        self.request.id,
    )
    use_case = IdentityProvider.build_enrich_session_use_case()
    outcome = use_case.execute(UUID(session_id))
    logger.info(
        "identity.enrich_user_session completed session_id=%s task_id=%s outcome=%s",
        session_id,
        self.request.id,
        outcome,
    )
    return outcome


@shared_task(
    name="identity.sweep_user_sessions",
    bind=True,
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    soft_time_limit=540,
    time_limit=600,
)
def sweep_user_sessions(self) -> dict[str, int]:
    """Daily session/audit janitor. Idempotent — pure reconciliation.

    1. Sessions past ``expires_at`` that were never revoked get
       ``revoked_reason="expired_sweep"`` (bookkeeping only — the refresh
       token is already unusable once expired).
    2. Sessions dead (revoked OR expired) for more than
       ``SESSION_RETENTION_DAYS`` are deleted.
    3. ``AuthAuditEvent`` rows older than ``AUTH_AUDIT_RETENTION_DAYS``
       are deleted in batches.
    """
    from django.conf import settings
    from django.db.models import Q
    from django.utils import timezone

    from infrastructure.persistence.users.models import AuthAuditEvent, UserSession

    logger.info("identity.sweep_user_sessions started task_id=%s", self.request.id)

    now = timezone.now()
    session_cutoff = now - timedelta(days=int(settings.SESSION_RETENTION_DAYS))
    audit_cutoff = now - timedelta(days=int(settings.AUTH_AUDIT_RETENTION_DAYS))

    # 1. Reconcile: expired but never revoked → revoked by sweep.
    expired_marked = UserSession.objects.filter(
        expires_at__lt=now,
        revoked_at__isnull=True,
    ).update(revoked_at=now, revoked_reason="expired_sweep")

    # 2. Prune sessions dead for > retention window. "Dead since" is the
    #    earlier of revocation / expiry, so either bound older than the
    #    cutoff qualifies. AuthAuditEvent.session is SET_NULL — history
    #    survives the session row.
    sessions_pruned, _ = UserSession.objects.filter(
        Q(revoked_at__lt=session_cutoff) | Q(expires_at__lt=session_cutoff)
    ).delete()

    # 3. Prune audit events past retention, batched so a first run over a
    #    large backlog doesn't materialise millions of pks at once.
    audit_pruned = 0
    while True:
        batch_ids = list(
            AuthAuditEvent.objects.filter(created_at__lt=audit_cutoff).values_list("pk", flat=True)[:_PRUNE_BATCH_SIZE]
        )
        if not batch_ids:
            break
        deleted, _ = AuthAuditEvent.objects.filter(pk__in=batch_ids).delete()
        audit_pruned += deleted

    result = {
        "expired_marked": expired_marked,
        "sessions_pruned": sessions_pruned,
        "audit_events_pruned": audit_pruned,
    }
    logger.info(
        "identity.sweep_user_sessions completed task_id=%s expired_marked=%d sessions_pruned=%d audit_pruned=%d",
        self.request.id,
        expired_marked,
        sessions_pruned,
        audit_pruned,
    )
    return result
