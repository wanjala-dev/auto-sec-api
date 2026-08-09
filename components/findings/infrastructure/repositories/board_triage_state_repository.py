"""Adapter: read findings' triage state off their board cards (``project.Task``).

Implements :class:`FindingTriageStatePort`. Mirrors the sanctioned cross-context
read pattern already used by ``report``'s ``BoardFindingRepository``: a read-only
port owned by the consuming context, whose adapter reads the shared persistence
model — never the other context's application or infrastructure code (C3).

Two queries for a whole page, regardless of page size (performance rule §1): one
indexed read of the page's cards, plus whatever the cadence lookup costs (nothing —
it is computed from settings).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from components.findings.application.ports.finding_triage_state_port import FindingTriageStatePort
from components.findings.application.queries.finding_triage_state_query import (
    FindingTriageStateView,
    derive_triage_state,
)
from components.shared_kernel.domain.triage import DISPATCH_STAMP_TTL_SECONDS, ROUTABLE_SOURCE_TYPES

logger = logging.getLogger(__name__)

# The beat entry that drives the cadence sweep. Prod/local name it
# ``schedule_ai_teammate_runs``; dev names the same task ``ai_teammate_schedule`` —
# both are accepted so ``next_triage_at`` is honest in every environment.
_CADENCE_ENTRY_NAMES = ("schedule_ai_teammate_runs", "ai_teammate_schedule")
_CADENCE_FALLBACK = timedelta(minutes=5)


class BoardTriageStateRepository(FindingTriageStatePort):
    def states_for(self, *, workspace_id, finding_ids: Sequence[str]) -> dict[str, FindingTriageStateView]:
        from infrastructure.persistence.project.models import Task

        ids = [str(f) for f in finding_ids if f]
        if not ids:
            return {}

        next_at = next_cadence_run_at()
        stale_before = timezone.now() - timedelta(seconds=DISPATCH_STAMP_TTL_SECONDS)

        states: dict[str, FindingTriageStateView] = {}
        rows = Task.objects.filter(
            workspace_id=workspace_id,
            source_type__in=ROUTABLE_SOURCE_TYPES,
            metadata__payload__finding_id__in=ids,
        ).only("id", "source_type", "metadata")

        for row in rows:
            metadata = row.metadata or {}
            finding_id = str(((metadata.get("payload") or {}).get("finding_id")) or "")
            if not finding_id:
                continue
            states[finding_id] = derive_triage_state(
                card={"source_type": row.source_type, "task_id": str(row.id), "metadata": metadata},
                next_triage_at=next_at,
                dispatch_stamp_is_fresh=_stamp_is_fresh(metadata.get("triage_dispatch"), stale_before),
            )
        return states


def _stamp_is_fresh(stamp, stale_before) -> bool:
    """True when an in-flight dispatch stamp is recent enough to still believe.

    A run that died leaves its stamp behind; past the TTL the finding honestly falls
    back to QUEUED (with the next cadence pass named) instead of spinning on
    DRAFTING forever.

    The stamp is a STRING on the card, written by whichever environment wrote it, so
    its awareness follows that deployment's ``USE_TZ`` — while ``stale_before`` follows
    THIS process's. Coercing only one side (the obvious version of this function)
    raises ``can't compare offset-naive and offset-aware datetimes`` the moment a
    stamp exists, which is exactly the DRAFTING path. Both sides are normalized here.
    """
    if not isinstance(stamp, dict):
        return False
    raw = str(stamp.get("at") or "")
    if not raw:
        return False
    try:
        at = datetime.fromisoformat(raw)
    except ValueError:
        return False
    return _match_awareness(at, stale_before) >= stale_before


def _match_awareness(value: datetime, reference: datetime) -> datetime:
    """Return *value* with the same naive/aware-ness as *reference*."""
    ref_aware = reference.tzinfo is not None
    val_aware = value.tzinfo is not None
    if ref_aware and not val_aware:
        return timezone.make_aware(value, timezone.get_default_timezone())
    if val_aware and not ref_aware:
        return timezone.make_naive(value, timezone.get_default_timezone())
    return value


def next_cadence_run_at(now: datetime | None = None) -> datetime | None:
    """When the finding-router cadence next sweeps — derived from the real beat schedule.

    Read from ``CELERY_BEAT_SCHEDULE`` rather than hard-coded, so the operator-facing
    "next pass ~HH:MM" cannot drift from what Beat actually does. Celery's schedule
    objects answer this directly via ``remaining_estimate``; a schedule shape that
    does not is degraded to the documented 5-minute cadence rather than dropping the
    promise entirely.
    """
    moment = now or timezone.now()
    schedule = getattr(settings, "CELERY_BEAT_SCHEDULE", {}) or {}
    for name in _CADENCE_ENTRY_NAMES:
        entry = schedule.get(name)
        if not isinstance(entry, dict):
            continue
        sched = entry.get("schedule")
        try:
            remaining = sched.remaining_estimate(moment)
        except Exception:
            logger.debug("next_cadence_run_at: entry=%s has no remaining_estimate", name, exc_info=True)
            return moment + _CADENCE_FALLBACK
        if isinstance(remaining, timedelta):
            # A crontab that just fired reports a non-positive estimate; roll to the
            # following slot so the operator is never shown a time in the past.
            return moment + (remaining if remaining.total_seconds() > 0 else _CADENCE_FALLBACK)
    return moment + _CADENCE_FALLBACK
