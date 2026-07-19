"""Operational visibility for the PaymentEvent ledger.

Lists PaymentEvent rows stuck in PROCESSING longer than the threshold
and (optionally) releases them back to RECEIVED so the next webhook
retry can pick them up. Use when investigating "donations not arriving"
reports — the most common cause is a Celery worker that crashed
mid-processing leaving an event holding a stale claim.

The 15-minute default mirrors the stale-claim recovery window in
``components/payments/infrastructure/adapters/payment_event_state.py``.
After that window, the next ``claim_payment_event_processing`` call
would already succeed against the row — this command makes the
inventory visible to ops without requiring SQL access.

Usage:
    # List events stuck > 15 min
    python manage.py audit_payment_events

    # Longer window
    python manage.py audit_payment_events --older-than-minutes 60

    # Release stale claims back to RECEIVED so retries pick them up
    python manage.py audit_payment_events --reset

    # Include FAILED rows in the inventory
    python manage.py audit_payment_events --include-failed
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = (
        "Audit the PaymentEvent idempotency ledger for stuck events "
        "(default: PROCESSING > 15 min). Pass --reset to release stale "
        "claims back to RECEIVED."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--older-than-minutes",
            type=int,
            default=15,
            help="Threshold age in minutes for considering an event stuck (default: 15).",
        )
        parser.add_argument(
            "--provider",
            type=str,
            default=None,
            help="Filter to a specific provider (e.g. 'stripe').",
        )
        parser.add_argument(
            "--include-failed",
            action="store_true",
            help="Also include events in FAILED status, not just PROCESSING.",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help=(
                "Release stale PROCESSING claims back to RECEIVED so the "
                "next webhook retry can pick them up. Does not touch FAILED."
            ),
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=200,
            help="Maximum rows to print / reset in a single run (default: 200).",
        )

    def handle(self, *args, **options) -> None:
        from infrastructure.persistence.workspaces.payments.models import PaymentEvent

        older_than = int(options["older_than_minutes"])
        provider = options["provider"]
        include_failed = bool(options["include_failed"])
        do_reset = bool(options["reset"])
        limit = int(options["limit"])

        threshold = timezone.now() - timedelta(minutes=older_than)

        statuses = [PaymentEvent.STATUS_PROCESSING]
        if include_failed:
            statuses.append(PaymentEvent.STATUS_FAILED)

        # processing_at is only stamped when claim_payment_event_processing
        # transitions the row into PROCESSING. FAILED rows may have it set
        # or may carry only created_at; we use created_at as the universal
        # age yardstick to keep the report consistent across both.
        qs = (
            PaymentEvent.objects.filter(status__in=statuses)
            .filter(created_at__lt=threshold)
            .order_by("created_at")
        )
        if provider:
            qs = qs.filter(provider=provider)
        qs = qs[:limit]

        rows = list(
            qs.values(
                "id",
                "provider",
                "provider_account_id",
                "event_id",
                "external_id",
                "event_type",
                "status",
                "status_message",
                "created_at",
                "processing_at",
            )
        )

        if not rows:
            self.stdout.write(
                self.style.SUCCESS(
                    f"No stuck PaymentEvents (status in {statuses}, "
                    f"older than {older_than} min)."
                )
            )
            return

        self.stdout.write(
            self.style.WARNING(
                f"Found {len(rows)} stuck PaymentEvent(s) (status in "
                f"{statuses}, older than {older_than} min):"
            )
        )
        for row in rows:
            age = (timezone.now() - row["created_at"]).total_seconds() / 60.0
            self.stdout.write(
                "  {id}  status={status:<10} provider={provider:<10} "
                "event_type={event_type:<40} event_id={event_id:<30} "
                "external_id={external_id:<30} age={age:.0f}m".format(
                    id=row["id"],
                    status=row["status"],
                    provider=row["provider"],
                    event_type=(row["event_type"] or "")[:40],
                    event_id=(row["event_id"] or "")[:30],
                    external_id=(row["external_id"] or "")[:30],
                    age=age,
                )
            )
            if row.get("status_message"):
                self.stdout.write(f"      message: {row['status_message']}")

        if do_reset:
            # Only release PROCESSING claims — FAILED is a terminal state
            # an operator must investigate explicitly. Idempotent: rerun
            # is safe.
            reset_ids = [r["id"] for r in rows if r["status"] == PaymentEvent.STATUS_PROCESSING]
            if reset_ids:
                updated = PaymentEvent.objects.filter(id__in=reset_ids).update(
                    status=PaymentEvent.STATUS_RECEIVED,
                    processing_at=None,
                    status_message="Released by audit_payment_events --reset",
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Released {updated} PROCESSING claim(s) back to RECEIVED."
                    )
                )
            else:
                self.stdout.write(
                    "No PROCESSING rows to reset (only FAILED matched the filter)."
                )
        else:
            self.stdout.write(
                "\nRun again with --reset to release PROCESSING claims back to RECEIVED."
            )
