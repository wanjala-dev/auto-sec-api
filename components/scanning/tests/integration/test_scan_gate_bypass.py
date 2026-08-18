"""Integration: the cooldown-exempt path through the scan dispatch gate (#118).

``bypass_cooldown`` exists for ONE caller — the post-merge verification rescan.
These tests pin its exact scope: the completed-run cooldown is skipped, but the
one-in-flight invariant and the queued-dispatch race lock still hold, and the
success-mirror lock (kept on a completed run so the cache mirrors the DB
cooldown) may be taken over ONLY when it provably belongs to a finished run.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone

from components.scanning.infrastructure.services.scan_gate import (
    check_and_lock_dispatch,
    dispatch_lock_key,
)
from infrastructure.persistence.scanning.models import ScanRun

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_SOURCE = "code_security.opengrep"
_REPO = "acme/app"
_COOLDOWN = 3600


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


def _run(ws, *, status, completed_delta=None, created_delta=None):
    now = timezone.now()
    run = ScanRun.objects.create(
        workspace=ws,
        source=_SOURCE,
        target_ref=_REPO,
        status=status,
        started_at=now - (created_delta or timedelta(0)),
        completed_at=(now - completed_delta) if completed_delta else None,
    )
    if created_delta:
        # created_at is auto_now_add; move it for the in-flight staleness window.
        ScanRun.objects.filter(id=run.id).update(created_at=now - created_delta)
    return run


def _gate(ws, *, bypass):
    return check_and_lock_dispatch(
        workspace_id=ws.id,
        source=_SOURCE,
        target_ref=_REPO,
        cooldown_seconds=_COOLDOWN,
        bypass_cooldown=bypass,
    )


def test_bypass_skips_the_completed_run_cooldown(workspace_factory):
    ws = workspace_factory()
    _run(ws, status=ScanRun.Status.COMPLETED, completed_delta=timedelta(minutes=10))

    # Control: the normal path is cooldown-locked...
    normal = _gate(ws, bypass=False)
    assert normal == {
        "allowed": False,
        "reason": "cooldown",
        "retry_after": normal["retry_after"],
        "last_scanned_at": normal["last_scanned_at"],
    }
    # ...the exempt path proceeds (and HOLDS the dispatch lock).
    exempt = _gate(ws, bypass=True)
    assert exempt["allowed"] is True
    assert cache.get(dispatch_lock_key(ws.id, _SOURCE, _REPO)) is not None


def test_bypass_never_breaks_the_one_in_flight_invariant(workspace_factory):
    ws = workspace_factory()
    _run(ws, status=ScanRun.Status.RUNNING)

    result = _gate(ws, bypass=True)

    assert result["allowed"] is False
    assert result["reason"] == "running"


def test_bypass_takes_over_only_the_success_mirror_lock(workspace_factory):
    """A lock whose timestamp predates the newest completion is the finished run's
    cooldown mirror — the exempt path may take it over and dispatch."""
    ws = workspace_factory()
    now = timezone.now()
    _run(ws, status=ScanRun.Status.COMPLETED, completed_delta=timedelta(minutes=10))
    # The lock the completed run's dispatch left behind (older than completion).
    cache.set(dispatch_lock_key(ws.id, _SOURCE, _REPO), (now - timedelta(minutes=20)).isoformat(), _COOLDOWN)

    result = _gate(ws, bypass=True)

    assert result["allowed"] is True
    # The lock was refreshed to THIS dispatch's timestamp.
    taken_over = cache.get(dispatch_lock_key(ws.id, _SOURCE, _REPO))
    assert taken_over is not None and taken_over >= now.isoformat()


def test_bypass_still_rejects_a_genuinely_queued_dispatch(workspace_factory):
    """A lock YOUNGER than the newest completion is a queued-but-unstarted dispatch
    (no run row yet) — even the exempt path must not double-dispatch."""
    ws = workspace_factory()
    now = timezone.now()
    _run(ws, status=ScanRun.Status.COMPLETED, completed_delta=timedelta(minutes=10))
    cache.set(dispatch_lock_key(ws.id, _SOURCE, _REPO), now.isoformat(), _COOLDOWN)

    result = _gate(ws, bypass=True)

    assert result["allowed"] is False
    assert result["reason"] == "running"


def test_bypass_with_a_lock_but_no_completed_run_rejects(workspace_factory):
    """No completed run at all → any held lock can only be a queued dispatch."""
    ws = workspace_factory()
    cache.set(dispatch_lock_key(ws.id, _SOURCE, _REPO), timezone.now().isoformat(), _COOLDOWN)

    result = _gate(ws, bypass=True)

    assert result["allowed"] is False
    assert result["reason"] == "running"


def test_default_path_behavior_is_unchanged(workspace_factory):
    """No bypass argument → byte-for-byte the pre-#118 contract (fresh target)."""
    ws = workspace_factory()

    result = check_and_lock_dispatch(workspace_id=ws.id, source=_SOURCE, target_ref=_REPO, cooldown_seconds=_COOLDOWN)

    assert result["allowed"] is True
    assert result["last_scanned_at"] is None
