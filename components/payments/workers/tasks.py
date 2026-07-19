"""Celery Beat entry points for the payments bounded context.

Beat-scheduled tasks are PRIMARY ADAPTERS — the scheduler is an external
trigger driving the application, just like an HTTP request or CLI command.
Each function should be a thin wrapper that delegates to an application
service or use case.

Tasks here:

* ``release_stuck_payment_events`` — janitor that flips
  ``PaymentEvent`` rows stuck in ``processing`` for more than 5 minutes back
  to ``received``. This recovers from worker crashes mid-processing: without
  this, the row stays claimed forever and Stripe re-deliveries are silently
  skipped because the unique-constraint dedupe sees the existing row.
* ``reconcile_stripe_events`` — pulls ``stripe.Event.list`` per Connect
  account every 15 minutes and replays anything we haven't recorded into
  the same idempotent ingest pipeline. This is the safety net for dropped
  webhooks (network blips, signature mismatches during a key rotation, etc).

Both tasks are safe to run concurrently with the live webhook flow because
they go through the same idempotency ledger (``unique_provider_event_id``
constraint).
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)

STUCK_PROCESSING_THRESHOLD = timedelta(minutes=5)
RECONCILIATION_LOOKBACK = timedelta(hours=2)


@shared_task(
    name="payments.release_stuck_payment_events",
    bind=True,
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    soft_time_limit=240,
    time_limit=300,
)
def release_stuck_payment_events(self) -> dict[str, int]:
    """Flip PaymentEvent rows stuck in PROCESSING > 5min back to RECEIVED.

    Why: when a worker claims a webhook event (status -> processing) and then
    crashes before marking it processed/failed, the row sits in PROCESSING
    forever. The next Stripe re-delivery hits the unique-constraint dedupe
    and is silently skipped because there's already a row for that event_id.
    Net effect: a single worker crash permanently loses the event.

    Strategy: any row that's been in PROCESSING longer than the threshold is
    almost certainly a crash victim — return it to RECEIVED so the next
    re-delivery (or the reconciliation task below) can process it.
    """
    from infrastructure.persistence.workspaces.payments.models import PaymentEvent

    cutoff = timezone.now() - STUCK_PROCESSING_THRESHOLD
    stuck = PaymentEvent.objects.filter(
        status=PaymentEvent.STATUS_PROCESSING,
        processing_at__lte=cutoff,
    )
    released = stuck.update(
        status=PaymentEvent.STATUS_RECEIVED,
        status_message="Released by janitor: processing exceeded 5min threshold",
    )
    if released:
        logger.warning(
            "payments.janitor.released_stuck count=%d cutoff=%s",
            released,
            cutoff.isoformat(),
        )
    return {"released": released}


@shared_task(
    name="payments.reconcile_stripe_events",
    bind=True,
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    soft_time_limit=240,
    time_limit=300,
)
def reconcile_stripe_events(self) -> dict[str, Any]:
    """Backfill missed Stripe events per Connect account.

    Webhooks can drop for many reasons — network blip, our worker rejected
    the signature during a key rotation, the request hit our 5xx mid-deploy,
    etc. Stripe will retry for ~3 days but if we keep 5xx-ing they give up.
    This task is the long-tail safety net: it pulls ``stripe.Event.list``
    per Connect account, filters by ``created`` window, and replays each
    unseen event into the same idempotent ingest pipeline.

    Idempotency is enforced by the existing
    ``unique_provider_event_id`` constraint on PaymentEvent — replaying
    an event we've already processed is a no-op.
    """
    import stripe
    from django.db import transaction

    from components.payments.infrastructure.adapters.payment_method_credentials import (
        read_payment_method_credentials,
    )
    from infrastructure.persistence.workspaces.payments.models import (
        PaymentEvent,
        WorkspacePaymentMethod,
    )

    since = int((timezone.now() - RECONCILIATION_LOOKBACK).timestamp())
    summary: dict[str, Any] = {"checked": 0, "replayed": 0, "errors": 0}

    methods = (
        WorkspacePaymentMethod.objects.select_related("provider", "workspace")
        .filter(
            provider__slug="stripe",
            status=WorkspacePaymentMethod.STATUS_ACTIVE,
            is_deleted=False,
        )
        .exclude(provider_account_id="")
    )

    for method in methods:
        summary["checked"] += 1
        try:
            credentials = read_payment_method_credentials(method)
        except Exception:  # noqa: BLE001 — credential decryption errors are loud upstream
            summary["errors"] += 1
            logger.exception(
                "payments.reconcile.credentials_error method_id=%s", method.id
            )
            continue

        api_key = credentials.get("secret_key")
        if not api_key:
            continue

        try:
            # Per-attempt request timeout is configured on the Stripe HTTP client
            # (configure_stripe_runtime); `timeout` is NOT a valid kwarg on a
            # stripe-python 5.x resource call (it 400s as an unknown parameter).
            events = stripe.Event.list(
                created={"gte": since},
                limit=100,
                api_key=api_key,
                stripe_account=method.provider_account_id or None,
            )
        except stripe.error.StripeError:
            summary["errors"] += 1
            logger.exception(
                "payments.reconcile.list_error method_id=%s", method.id
            )
            continue

        for event in getattr(events, "auto_paging_iter", lambda: events.data)():
            event_id = event.get("id") if isinstance(event, dict) else getattr(event, "id", None)
            if not event_id:
                continue

            already_seen = PaymentEvent.objects.filter(
                provider="stripe",
                event_id=event_id,
            ).exists()
            if already_seen:
                continue

            # We see an event that didn't make it through the live webhook
            # path. Insert a RECEIVED row and let the existing route+process
            # pipeline pick it up on the next janitor pass / scheduler tick.
            # We deliberately do NOT call the synchronous handler here — the
            # whole point of reconciliation is to land the event safely in the
            # ledger, not re-architect the processing path.
            try:
                with transaction.atomic():
                    PaymentEvent.objects.create(
                        provider="stripe",
                        provider_account_id=method.provider_account_id or "",
                        workspace=method.workspace,
                        method=method,
                        event_id=event_id,
                        event_type=(
                            event.get("type")
                            if isinstance(event, dict)
                            else getattr(event, "type", "")
                        ),
                        payload=event if isinstance(event, dict) else dict(event),
                        status=PaymentEvent.STATUS_RECEIVED,
                        status_message="Backfilled by reconciliation task",
                    )
                summary["replayed"] += 1
            except Exception:  # noqa: BLE001
                # Likely a race with the live webhook landing first; the
                # unique constraint takes care of dedupe.
                logger.debug(
                    "payments.reconcile.insert_skipped event_id=%s", event_id
                )

    if summary["replayed"] or summary["errors"]:
        logger.warning(
            "payments.reconcile.summary checked=%d replayed=%d errors=%d",
            summary["checked"],
            summary["replayed"],
            summary["errors"],
        )
    return summary


# Event types the team-plan webhook handler cares about. Source of truth:
# components/payments/infrastructure/repositories/team_plan_webhook_repository.py
# (the dispatch dict near the top). We also include subscription.created so
# the platform side can backfill new subscriptions, even though the live
# handler doesn't act on that event today — having the row in the ledger
# makes future event-type additions a no-op replay.
_TEAM_PLAN_EVENT_TYPES = (
    "checkout.session.completed",
    "checkout.session.expired",
    "invoice.payment_succeeded",
    "invoice.payment_failed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
)


@shared_task(
    name="payments.reconcile_team_plan_stripe_events",
    bind=True,
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    soft_time_limit=240,
    time_limit=300,
)
def reconcile_team_plan_stripe_events(self) -> dict[str, Any]:
    """Backfill missed Stripe events for the platform-account team-plan flow.

    Mirror of ``reconcile_stripe_events`` but for the OPPOSITE side of the
    money flow: this one talks to the platform Stripe account (no Connect
    ``stripe_account`` kwarg) using the global ``STRIPE_SECRET_KEY``. The
    team-plan webhook URL ``/workspaces/payments/stripe/webhook/`` is what
    drives our SaaS subscription billing — losing one of those events means
    losing real revenue tracking, so the safety net here is just as
    important as the donation side.

    Idempotency is enforced by the existing ``unique_provider_event_id``
    constraint on PaymentEvent — replaying an event we've already processed
    is a no-op.
    """
    import stripe
    from django.conf import settings
    from django.db import transaction

    from infrastructure.persistence.workspaces.payments.models import PaymentEvent

    summary: dict[str, Any] = {"checked": 0, "replayed": 0, "errors": 0}

    api_key = getattr(settings, "STRIPE_SECRET_KEY", None)
    if not api_key:
        logger.warning(
            "payments.reconcile_team_plan.skipped reason=no_stripe_secret_key"
        )
        summary["errors"] += 1
        return summary

    since = int((timezone.now() - RECONCILIATION_LOOKBACK).timestamp())

    try:
        # Per-attempt request timeout is on the Stripe HTTP client
        # (configure_stripe_runtime); `timeout` is not a valid resource-call kwarg.
        events = stripe.Event.list(
            created={"gte": since},
            limit=100,
            api_key=api_key,
        )
    except stripe.error.StripeError:
        summary["errors"] += 1
        logger.exception("payments.reconcile_team_plan.list_error")
        return summary

    iterator = getattr(events, "auto_paging_iter", lambda: events.data)()
    for event in iterator:
        summary["checked"] += 1
        event_id = (
            event.get("id") if isinstance(event, dict) else getattr(event, "id", None)
        )
        if not event_id:
            continue

        event_type = (
            event.get("type")
            if isinstance(event, dict)
            else getattr(event, "type", "")
        )
        if event_type not in _TEAM_PLAN_EVENT_TYPES:
            continue

        already_seen = PaymentEvent.objects.filter(
            provider="stripe",
            event_id=event_id,
        ).exists()
        if already_seen:
            continue

        try:
            with transaction.atomic():
                PaymentEvent.objects.create(
                    provider="stripe",
                    # Empty provider_account_id distinguishes platform-account
                    # team-plan rows from per-workspace Connect rows. The
                    # team-plan webhook handler tolerates workspace=None +
                    # method=None (see team_plan_webhook_repository).
                    provider_account_id="",
                    workspace=None,
                    method=None,
                    event_id=event_id,
                    event_type=event_type,
                    payload=event if isinstance(event, dict) else dict(event),
                    status=PaymentEvent.STATUS_RECEIVED,
                    status_message="Backfilled by team-plan reconciliation task",
                )
            summary["replayed"] += 1
        except Exception:  # noqa: BLE001
            # Race with the live webhook landing first; unique constraint
            # makes this safe to swallow.
            logger.debug(
                "payments.reconcile_team_plan.insert_skipped event_id=%s",
                event_id,
            )

    if summary["replayed"] or summary["errors"]:
        logger.warning(
            "payments.reconcile_team_plan.summary checked=%d replayed=%d errors=%d",
            summary["checked"],
            summary["replayed"],
            summary["errors"],
        )
    return summary
