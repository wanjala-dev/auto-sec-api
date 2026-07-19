"""Adapter: pulls per-workspace metrics for newsletter generation.

Implements ``NewsletterMetricsCollectorPort`` declared by
``DispatchScheduledNewslettersUseCase``. Runs inside the Celery task
(per the Heavy-Aggregations HARD RULE) so the aggregation cost stays
off the web tier.

SEE-174: this used to be a counts-only stub — and worse, two of its three
sub-queries were silently broken (they filtered ``created`` / ``date``,
fields that do not exist on ``Donation`` / ``Event`` — the real columns
are ``created_at`` / ``start_date``), so the ``FieldError`` was swallowed
by the per-section ``except`` and donations + events always degraded to
``0`` regardless of activity. That fed the deep-planner thin numbers and
produced the audited "empty shell" newsletter.

It now returns real, grounded aggregates for the period: donation **sum**
+ count, **top donors** (named, amount), **new recipients with names**,
**recent + upcoming events**, **active programs**, and a cheap
period-over-period donation delta. The keys are emitted FLAT
(``donations_total``, ``donations_count``, ``new_recipients`` …) so the
block composer's KPI cards and the deterministic grounded-summary
fallback can read them directly.

Posture (unchanged): workspace-scoped for tenancy safety, best-effort —
every sub-query is wrapped so a broken aggregation degrades to omitting
that metric, never crashing the whole payload. ORM imports are inline to
keep module-load-time free of Django.
"""

from __future__ import annotations

import datetime
import logging
from decimal import Decimal
from uuid import UUID

logger = logging.getLogger(__name__)

# How many named donors / recipient names / events / projects to surface.
# Small caps keep the grounding payload compact and the prose readable.
_TOP_DONORS = 3
_MAX_NAMES = 8
_MAX_EVENTS = 5
_MAX_PROJECTS = 5


class NewsletterMetricsCollectorAdapter:
    def collect(
        self,
        *,
        workspace_id: UUID,
        period_start: datetime.date,
        period_end: datetime.date,
    ) -> dict:
        metrics: dict = {
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
        }

        self._collect_donations(metrics, workspace_id, period_start, period_end)
        self._collect_recipients(metrics, workspace_id, period_start, period_end)
        self._collect_events(metrics, workspace_id, period_start, period_end)
        self._collect_projects(metrics, workspace_id)

        return metrics

    # ── donations ───────────────────────────────────────────────────────

    def _collect_donations(
        self,
        metrics: dict,
        workspace_id: UUID,
        period_start: datetime.date,
        period_end: datetime.date,
    ) -> None:
        try:
            from django.db.models import Count, Sum

            from infrastructure.persistence.sponsorship.donations.models import (
                Donation,
            )

            qs = Donation.objects.filter(
                workspace_id=workspace_id,
                created_at__date__gte=period_start,
                created_at__date__lte=period_end,
            )
            agg = qs.aggregate(total=Sum("amount"), count=Count("id"))
            total = agg.get("total") or Decimal("0")
            metrics["donations_total"] = self._money(total)
            metrics["donations_count"] = int(agg.get("count") or 0)

            currency = (
                qs.exclude(currency__isnull=True)
                .exclude(currency="")
                .values_list("currency", flat=True)
                .first()
            )
            if currency:
                metrics["currency"] = currency

            top = (
                qs.exclude(is_anonymous=True)
                .exclude(name__isnull=True)
                .exclude(name="")
                .values("name")
                .annotate(total=Sum("amount"))
                .order_by("-total")[:_TOP_DONORS]
            )
            top_donors = [
                {"name": row["name"], "amount": self._money(row["total"])}
                for row in top
                if row.get("total")
            ]
            if top_donors:
                metrics["top_donors"] = top_donors
        except Exception:  # noqa: BLE001 — best-effort metric; omit on failure
            logger.exception(
                "metrics donations collection failed workspace_id=%s",
                workspace_id,
            )

        # Period-over-period delta — the immediately preceding window of
        # equal length. Cheap (one Sum) and grounds a "up/down vs last
        # period" line. Kept separate so a delta failure never loses the
        # primary donation totals above.
        try:
            from django.db.models import Sum

            from infrastructure.persistence.sponsorship.donations.models import (
                Donation,
            )

            span = (period_end - period_start).days + 1
            prev_end = period_start - datetime.timedelta(days=1)
            prev_start = prev_end - datetime.timedelta(days=span - 1)
            prev_total = (
                Donation.objects.filter(
                    workspace_id=workspace_id,
                    created_at__date__gte=prev_start,
                    created_at__date__lte=prev_end,
                ).aggregate(total=Sum("amount"))
                .get("total")
                or Decimal("0")
            )
            metrics["donations_total_prev"] = self._money(prev_total)
            current = Decimal(str(metrics.get("donations_total") or "0"))
            if prev_total and prev_total > 0:
                delta_pct = (current - prev_total) / prev_total * Decimal("100")
                metrics["donations_delta_pct"] = int(delta_pct.to_integral_value())
        except Exception:  # noqa: BLE001
            logger.exception(
                "metrics donation delta collection failed workspace_id=%s",
                workspace_id,
            )

    # ── recipients ──────────────────────────────────────────────────────

    def _collect_recipients(
        self,
        metrics: dict,
        workspace_id: UUID,
        period_start: datetime.date,
        period_end: datetime.date,
    ) -> None:
        try:
            from infrastructure.persistence.sponsorship.recipients.models import (
                Recipient,
            )

            new_qs = Recipient.objects.filter(
                workspace_id=workspace_id,
                created_at__date__gte=period_start,
                created_at__date__lte=period_end,
            )
            names: list[str] = []
            for rec in new_qs.only("first_name", "last_name")[:_MAX_NAMES]:
                name = " ".join(
                    p for p in (rec.first_name, rec.last_name) if p
                ).strip()
                if name:
                    names.append(name)
            metrics["new_recipients"] = new_qs.count()
            if names:
                metrics["new_recipient_names"] = names

            metrics["recipient_count"] = Recipient.objects.filter(
                workspace_id=workspace_id
            ).count()
        except Exception:  # noqa: BLE001
            logger.exception(
                "metrics recipients collection failed workspace_id=%s",
                workspace_id,
            )

    # ── events ──────────────────────────────────────────────────────────

    def _collect_events(
        self,
        metrics: dict,
        workspace_id: UUID,
        period_start: datetime.date,
        period_end: datetime.date,
    ) -> None:
        try:
            from django.db.models import Sum

            from infrastructure.persistence.sponsorship.events.models import Event

            recent = (
                Event.objects.filter(
                    workspace_id=workspace_id,
                    start_date__date__gte=period_start,
                    start_date__date__lte=period_end,
                )
                .order_by("-start_date")[:_MAX_EVENTS]
            )
            recent_events = []
            for evt in recent:
                raised = evt.donations.aggregate(total=Sum("amount")).get("total")
                entry: dict = {"title": evt.title}
                if evt.start_date:
                    entry["date"] = evt.start_date.date().isoformat()
                if raised:
                    entry["raised"] = self._money(raised)
                recent_events.append(entry)
            if recent_events:
                metrics["recent_events"] = recent_events

            upcoming_qs = Event.objects.filter(
                workspace_id=workspace_id,
                start_date__date__gt=period_end,
            ).order_by("start_date")
            upcoming = []
            for evt in upcoming_qs[:_MAX_EVENTS]:
                entry = {"title": evt.title}
                if evt.start_date:
                    entry["date"] = evt.start_date.date().isoformat()
                upcoming.append(entry)
            if upcoming:
                metrics["upcoming_events"] = upcoming
            metrics["upcoming_events_count"] = upcoming_qs.count()
        except Exception:  # noqa: BLE001
            logger.exception(
                "metrics events collection failed workspace_id=%s",
                workspace_id,
            )

    # ── projects / programs ─────────────────────────────────────────────

    def _collect_projects(self, metrics: dict, workspace_id: UUID) -> None:
        try:
            from infrastructure.persistence.project.models import Project

            projects = (
                Project.objects.filter(workspace_id=workspace_id)
                .select_related()
                .order_by("-created_at")[:_MAX_PROJECTS]
            )
            active = []
            for proj in projects:
                entry = {"title": proj.title}
                display = getattr(proj, "get_status_display", None)
                if callable(display):
                    try:
                        entry["status"] = str(display() or "")
                    except Exception:  # noqa: BLE001
                        pass
                active.append(entry)
            if active:
                metrics["active_projects"] = active
        except Exception:  # noqa: BLE001
            logger.exception(
                "metrics projects collection failed workspace_id=%s",
                workspace_id,
            )

    # ── helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _money(value: object) -> str:
        """Normalise a money value to a plain ``str(Decimal)`` (no FX).

        Stored as a string so JSON round-trips losslessly and the block
        composer / faithfulness verifier compare the exact figure the
        ledger holds.
        """
        try:
            dec = Decimal(str(value or "0"))
        except Exception:  # noqa: BLE001
            return "0"
        # Strip trailing fractional zeros for clean display ("50000.00" →
        # "50000") so the grounded copy reads naturally and the verifier's
        # value-based comparison matches.
        normalized = dec.quantize(Decimal("0.01")) if dec % 1 else dec.to_integral_value()
        text = format(normalized, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text
