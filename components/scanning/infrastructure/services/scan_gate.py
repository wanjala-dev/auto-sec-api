"""The scan dispatch gate + per-target scan history — the infrastructure half.

Implementation behind ``application/providers/scan_gate_provider`` (the published
seam pillars call). Lives in infrastructure because it touches the ORM, the
Django cache, and ``timezone`` — none of which belong in the application layer.

Pillars call the provider BEFORE ``dispatch_scan`` to enforce the anti-spam
budget (ADR 0019 D3: cost/noise controls): one scan per (workspace, source,
target) per cooldown window, and never more than one in flight. The scanning
context owns the ``ScanRun`` history, so the authority lives here — a pillar
never reads another context's run rows.

Two layers, fail-closed:

1. **The run history (authoritative).** A PENDING/RUNNING run → ``running``; a
   COMPLETED run younger than the cooldown → ``cooldown`` (with ``retry_after``).
   FAILED runs do NOT start a cooldown — a transient failure must not lock the
   target for an hour.
2. **A dispatch lock (the race-closer).** ``cache.add`` (atomic) covers the
   queued-but-not-yet-started window where no run row exists yet. TTL = the
   cooldown; the generic scan task RELEASES it on a failed run (retry allowed),
   keeps it on success (the lock then mirrors the DB cooldown even if the row
   read is raced).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

# A run stuck in PENDING/RUNNING older than this is treated as dead (a crashed
# worker must not lock the target forever); the Job's own deadline is far below.
_STALE_RUNNING_SECONDS = 30 * 60


def dispatch_lock_key(workspace_id, source: str, target_ref: str) -> str:
    return f"scanning:dispatch_lock:{workspace_id}:{source}:{target_ref}"


def release_dispatch_lock(*, workspace_id, source: str, target_ref: str) -> None:
    """Free the lock (the generic scan task calls this on a FAILED run so the
    operator can retry without waiting out the cooldown)."""
    cache.delete(dispatch_lock_key(workspace_id, source, target_ref))


def _lock_predates_completion(lock_key: str, last_completed) -> bool:
    """True when the held dispatch lock belongs to a run that has ALREADY completed.

    The lock value is the dispatch timestamp. If it is older than the newest
    completed run's ``completed_at``, the lock is that run's success mirror (kept
    deliberately so the cache mirrors the DB cooldown) — NOT a queued-but-unstarted
    dispatch. Anything unparseable/missing is treated as contended (fail closed)."""
    if last_completed is None or last_completed.completed_at is None:
        return False
    raw = cache.get(lock_key)
    if not raw:
        return False
    try:
        locked_at = datetime.fromisoformat(str(raw))
    except ValueError:
        return False
    if timezone.is_naive(locked_at):
        locked_at = timezone.make_aware(locked_at, UTC)
    return locked_at <= last_completed.completed_at


def check_and_lock_dispatch(
    *, workspace_id, source: str, target_ref: str, cooldown_seconds: int, bypass_cooldown: bool = False
) -> dict:
    """Gate one dispatch. Returns ``{"allowed": bool, "reason", "retry_after", "last_scanned_at"}``.

    On ``allowed=True`` the dispatch lock is HELD — the caller must proceed to
    ``dispatch_scan`` (or call ``release_dispatch_lock`` if it aborts).

    ``bypass_cooldown`` (#118 — the post-merge verification rescan) skips ONLY the
    completed-run cooldown window; the one-in-flight invariant and the queued-race
    lock still hold. It is deliberately narrow: the sole caller is the
    merge-triggered rescan task — scheduled and manual triggers never pass it.
    """
    from infrastructure.persistence.scanning.models import ScanRun

    now = timezone.now()
    runs = ScanRun.objects.filter(workspace_id=workspace_id, source=source, target_ref=target_ref)

    in_flight = (
        runs.filter(
            status__in=(ScanRun.Status.PENDING, ScanRun.Status.RUNNING),
            created_at__gte=now - timedelta(seconds=_STALE_RUNNING_SECONDS),
        )
        .order_by("-created_at")
        .first()
    )
    if in_flight is not None:
        return {"allowed": False, "reason": "running", "retry_after": None, "last_scanned_at": None}

    last_completed = runs.filter(status=ScanRun.Status.COMPLETED).order_by("-completed_at").first()
    if last_completed is not None and last_completed.completed_at is not None and not bypass_cooldown:
        elapsed = (now - last_completed.completed_at).total_seconds()
        if elapsed < cooldown_seconds:
            return {
                "allowed": False,
                "reason": "cooldown",
                "retry_after": int(cooldown_seconds - elapsed),
                "last_scanned_at": last_completed.completed_at,
            }

    # Atomic race-closer for the queued-not-yet-started window. add() returns
    # False when the key already exists → another dispatch is already queued —
    # OR (success path) the previous completed run's lock is still mirroring the
    # DB cooldown. A cooldown-bypassing caller may take over ONLY the latter:
    # a lock provably older than the newest completion is cooldown residue, while
    # a younger one is a genuinely queued dispatch and still rejects.
    lock_key = dispatch_lock_key(workspace_id, source, target_ref)
    acquired = cache.add(lock_key, now.isoformat(), cooldown_seconds)
    if not acquired:
        if bypass_cooldown and _lock_predates_completion(lock_key, last_completed):
            cache.set(lock_key, now.isoformat(), cooldown_seconds)
        else:
            return {"allowed": False, "reason": "running", "retry_after": None, "last_scanned_at": None}
    return {
        "allowed": True,
        "reason": "",
        "retry_after": None,
        "last_scanned_at": last_completed.completed_at if last_completed else None,
    }


def count_in_flight(source: str) -> int:
    """How many scans of ``source`` are queued or running RIGHT NOW.

    The fleet-wide companion to the per-target gate above, and it reads the same
    authority (``ScanRun`` rows) with the same staleness rule — a run stuck in
    PENDING/RUNNING past ``_STALE_RUNNING_SECONDS`` belongs to a crashed worker
    and must not hold a concurrency slot forever.

    Deliberately NOT workspace-scoped: the resource this bounds is the scanner
    cluster and the shared cloud-provider API budget, both of which every
    workspace draws from. A per-workspace ceiling would let ten customers each
    dispatch the maximum simultaneously — exactly the herd it exists to stop.
    (Within one database: a dedicated-tier tenant's runs live in its own, so the
    ceiling applies per database. Noted with the beat fan-out gap in the PR.)
    """
    from infrastructure.persistence.scanning.models import ScanRun

    now = timezone.now()
    return ScanRun.objects.filter(
        source=source,
        status__in=(ScanRun.Status.PENDING, ScanRun.Status.RUNNING),
        created_at__gte=now - timedelta(seconds=_STALE_RUNNING_SECONDS),
    ).count()


def latest_runs_for(workspace_id, source: str, target_refs: list[str]) -> dict[str, dict]:
    """Per-target scan status for a pillar's history/read surface.

    Returns ``{target_ref: {last_scanned_at, last_status, last_run_id,
    duration_seconds, trigger, triggered_by_id, in_flight}}`` — the newest run's
    facts per target (and whether one is currently queued/running). One query.
    """
    from infrastructure.persistence.scanning.models import ScanRun

    result: dict[str, dict] = {}
    if not target_refs:
        return result
    runs = ScanRun.objects.filter(workspace_id=workspace_id, source=source, target_ref__in=target_refs).order_by(
        "target_ref", "-created_at"
    )
    for run in runs:
        entry = result.get(run.target_ref)
        if entry is None:
            duration = None
            if run.started_at and run.completed_at:
                duration = int((run.completed_at - run.started_at).total_seconds())
            result[run.target_ref] = {
                "last_scanned_at": run.completed_at or run.started_at or run.created_at,
                "last_status": run.status,
                "last_run_id": str(run.id),
                "duration_seconds": duration,
                "trigger": run.trigger,
                "triggered_by_id": str(run.triggered_by_id) if run.triggered_by_id else None,
                "in_flight": run.status in (ScanRun.Status.PENDING, ScanRun.Status.RUNNING),
            }
    return result
