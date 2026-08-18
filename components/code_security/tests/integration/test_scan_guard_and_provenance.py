"""Integration: the anti-spam dispatch gate + scan provenance (ADR 0019 D3).

Back-to-back SCAN clicks must be rejected server-side (one in-flight scan per
repo, one completed scan per cooldown window), failed scans must not lock the
repo, and every run row carries who/what triggered it. Also pins the CODE REPOS
status read (last-scanned + cooldown + provenance per repo).
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.utils import timezone

from components.code_security.application.use_cases.list_repo_scan_status_use_case import (
    ListRepoScanStatusUseCase,
)
from components.code_security.application.use_cases.trigger_repo_scan_use_case import (
    RepoScanRejected,
    TriggerRepoScanUseCase,
)
from components.scanning.application.providers import scan_dispatch_provider
from components.scanning.application.providers.scan_gate_provider import (
    check_and_lock_dispatch,
    release_dispatch_lock,
)
from infrastructure.persistence.integrations.models import VcsConnection
from infrastructure.persistence.scanning.models import ScanRun

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_SOURCE = "code_security.opengrep"
_REPO = "wanjala-dev/auto-sec-api"
_COOLDOWN = 3600


class _FakeAsyncResult:
    id = "task-1"


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture()
def _dispatch_spy(monkeypatch):
    calls = []

    def _fake_dispatch(**kwargs):
        calls.append(kwargs)
        return _FakeAsyncResult()

    monkeypatch.setattr(scan_dispatch_provider, "dispatch_scan", _fake_dispatch)
    return calls


def _connection(ws):
    return VcsConnection.objects.create(
        workspace=ws,
        provider=VcsConnection.Provider.GITHUB,
        name="GitHub",
        repo_allowlist=[_REPO],
        status=VcsConnection.Status.CONNECTED,
    )


def _run(ws, *, status, completed_delta=None, started_delta=None, trigger="manual", triggered_by=None):
    now = timezone.now()
    return ScanRun.objects.create(
        workspace=ws,
        source=_SOURCE,
        target_ref=_REPO,
        status=status,
        trigger=trigger,
        triggered_by_id=triggered_by,
        started_at=(now - started_delta) if started_delta else now,
        completed_at=(now - completed_delta) if completed_delta else None,
    )


def test_back_to_back_scans_second_dispatch_is_rejected(workspace_factory, _dispatch_spy):
    """The spam case: two SCAN clicks in a row → one enqueue, one 429-shaped reject."""
    ws = workspace_factory()
    _connection(ws)
    use_case = TriggerRepoScanUseCase()

    first = use_case.execute(workspace_id=ws.id, repo=_REPO, triggered_by=uuid4())
    assert first["task_id"] == "task-1"
    assert len(_dispatch_spy) == 1

    with pytest.raises(RepoScanRejected) as excinfo:
        use_case.execute(workspace_id=ws.id, repo=_REPO)
    assert excinfo.value.code == "scan_already_running"
    assert len(_dispatch_spy) == 1, "the second click must not enqueue"


def test_cooldown_locks_a_repo_for_the_window(workspace_factory, _dispatch_spy):
    """A repo completed 10 minutes ago is locked (~1h window) with retry_after."""
    ws = workspace_factory()
    _connection(ws)
    _run(ws, status=ScanRun.Status.COMPLETED, completed_delta=timedelta(minutes=10))

    with pytest.raises(RepoScanRejected) as excinfo:
        TriggerRepoScanUseCase().execute(workspace_id=ws.id, repo=_REPO)
    assert excinfo.value.code == "scan_cooldown"
    assert 0 < excinfo.value.retry_after <= _COOLDOWN
    assert _dispatch_spy == []


def test_cooldown_expires_after_the_window(workspace_factory, _dispatch_spy):
    ws = workspace_factory()
    _connection(ws)
    _run(ws, status=ScanRun.Status.COMPLETED, completed_delta=timedelta(hours=2))

    result = TriggerRepoScanUseCase().execute(workspace_id=ws.id, repo=_REPO)
    assert result["repo"] == _REPO
    assert len(_dispatch_spy) == 1


def test_in_flight_run_blocks_a_new_dispatch(workspace_factory, _dispatch_spy):
    ws = workspace_factory()
    _connection(ws)
    _run(ws, status=ScanRun.Status.RUNNING)

    with pytest.raises(RepoScanRejected) as excinfo:
        TriggerRepoScanUseCase().execute(workspace_id=ws.id, repo=_REPO)
    assert excinfo.value.code == "scan_already_running"
    assert _dispatch_spy == []


def test_failed_scan_does_not_start_a_cooldown(workspace_factory, _dispatch_spy):
    """A transient engine failure must not lock the repo for an hour."""
    ws = workspace_factory()
    _connection(ws)
    _run(ws, status=ScanRun.Status.FAILED, started_delta=timedelta(minutes=5))
    # the generic task releases the dispatch lock on the fail-loud path
    release_dispatch_lock(workspace_id=str(ws.id), source=_SOURCE, target_ref=_REPO)

    result = TriggerRepoScanUseCase().execute(workspace_id=ws.id, repo=_REPO)
    assert result["repo"] == _REPO
    assert len(_dispatch_spy) == 1


def test_gate_is_per_repo_and_per_workspace(workspace_factory, _dispatch_spy):
    """The lock scopes to (workspace, source, target) — no cross-tenant bleed."""
    ws_a = workspace_factory()
    ws_b = workspace_factory()
    _connection(ws_a)
    _connection(ws_b)

    TriggerRepoScanUseCase().execute(workspace_id=ws_a.id, repo=_REPO)
    # same repo name, other workspace → allowed
    result = TriggerRepoScanUseCase().execute(workspace_id=ws_b.id, repo=_REPO)
    assert result["repo"] == _REPO
    assert len(_dispatch_spy) == 2


def test_gate_provider_contract_direct():
    """The scanning-owned gate: allowed=True holds the lock; a second call bounces."""
    ws_id = str(uuid4())
    first = check_and_lock_dispatch(workspace_id=ws_id, source=_SOURCE, target_ref=_REPO, cooldown_seconds=_COOLDOWN)
    assert first["allowed"] is True
    second = check_and_lock_dispatch(workspace_id=ws_id, source=_SOURCE, target_ref=_REPO, cooldown_seconds=_COOLDOWN)
    assert second["allowed"] is False and second["reason"] == "running"
    release_dispatch_lock(workspace_id=ws_id, source=_SOURCE, target_ref=_REPO)
    third = check_and_lock_dispatch(workspace_id=ws_id, source=_SOURCE, target_ref=_REPO, cooldown_seconds=_COOLDOWN)
    assert third["allowed"] is True


def test_run_rows_carry_trigger_provenance(workspace_factory, _dispatch_spy):
    """Manual dispatches stamp trigger=manual + the operator's user id into the
    dispatch kwargs (the choreography writes them onto the ScanRun row)."""
    ws = workspace_factory()
    _connection(ws)
    operator = uuid4()

    TriggerRepoScanUseCase().execute(workspace_id=ws.id, repo=_REPO, triggered_by=operator)
    assert _dispatch_spy[0]["trigger"] == "manual"
    assert _dispatch_spy[0]["triggered_by"] == str(operator)


def test_choreography_persists_provenance_on_the_run_row(workspace_factory):
    from components.scanning.infrastructure.services.run_scan_service import run_scan_and_ingest
    from components.shared_kernel.application.ports.scanner_port import ScanResult, ScanTarget

    class _StubScanner:
        def scan(self, target, on_progress=None):
            return ScanResult(findings=(), engine="opengrep", engine_version="1.26.0")

    class _NullPublisher:
        def publish(self, event):
            pass

    ws = workspace_factory()
    operator = uuid4()
    run = run_scan_and_ingest(
        workspace_id=ws.id,
        source=_SOURCE,
        target=ScanTarget(identifier=_REPO),
        scanner=_StubScanner(),
        trigger="manual",
        triggered_by=str(operator),
        event_publisher=_NullPublisher(),
    )
    run.refresh_from_db()
    assert run.trigger == "manual"
    assert run.triggered_by_id == operator
    assert run.started_at is not None and run.completed_at is not None


def test_repo_status_read_surfaces_last_scan_and_cooldown(workspace_factory):
    """The CODE REPOS card read: last-scanned + duration + provenance + countdown."""
    ws = workspace_factory()
    connection = _connection(ws)
    operator = uuid4()
    _run(
        ws,
        status=ScanRun.Status.COMPLETED,
        completed_delta=timedelta(minutes=10),
        started_delta=timedelta(minutes=11),
        trigger="manual",
        triggered_by=operator,
    )

    rows = ListRepoScanStatusUseCase().execute(workspace_id=ws.id, cooldown_seconds=_COOLDOWN)
    row = next(r for r in rows if r["repo"] == _REPO)
    assert row["connection_id"] == str(connection.id)
    assert row["last_status"] == "completed"
    assert row["last_scanned_at"] is not None
    assert row["duration_seconds"] == 60
    assert row["trigger"] == "manual"
    assert row["triggered_by_id"] == str(operator)
    assert row["in_flight"] is False
    assert 0 < row["cooldown_remaining"] <= _COOLDOWN


def test_repo_status_read_never_scanned(workspace_factory):
    ws = workspace_factory()
    _connection(ws)
    rows = ListRepoScanStatusUseCase().execute(workspace_id=ws.id, cooldown_seconds=_COOLDOWN)
    row = next(r for r in rows if r["repo"] == _REPO)
    assert row["last_scanned_at"] is None
    assert row["cooldown_remaining"] == 0
    assert row["in_flight"] is False
    assert row["last_snapshot"] is None


def _snapshot(ws, repo, *, total, critical=0, high=0, medium=0, low=0, age=timedelta()):
    from infrastructure.persistence.code_security.models import RepoScanSnapshot

    row = RepoScanSnapshot.objects.create(
        workspace=ws,
        scan_run_id=uuid4(),
        repo=repo,
        commit_sha="a" * 40,
        engine_version="1.26.0",
        total_findings=total,
        critical_count=critical,
        high_count=high,
        medium_count=medium,
        low_count=low,
    )
    if age:
        # auto_now_add stamps creation time; push older rows back explicitly.
        RepoScanSnapshot.objects.filter(pk=row.pk).update(created_at=timezone.now() - age)
        row.refresh_from_db()
    return row


def test_repo_status_read_carries_latest_snapshot_counts(workspace_factory):
    """Every repo row surfaces its LATEST completed run's severity counts inline
    (the admin sees vulnerability state without a click) — newest snapshot wins."""
    ws = workspace_factory()
    _connection(ws)
    _run(ws, status=ScanRun.Status.COMPLETED, completed_delta=timedelta(minutes=10))
    _snapshot(ws, _REPO, total=9, critical=3, high=6, age=timedelta(hours=2))
    newest = _snapshot(ws, _REPO, total=16, medium=16)

    rows = ListRepoScanStatusUseCase().execute(workspace_id=ws.id, cooldown_seconds=_COOLDOWN)
    row = next(r for r in rows if r["repo"] == _REPO)
    snapshot = row["last_snapshot"]
    assert snapshot is not None
    assert snapshot["scan_run_id"] == str(newest.scan_run_id)
    assert snapshot["total_findings"] == 16
    assert snapshot["critical_count"] == 0
    assert snapshot["medium_count"] == 16
    assert snapshot["commit_sha"] == "a" * 40
    assert snapshot["engine_version"] == "1.26.0"
    # Aware-UTC stamp — never a naive ISO the frontend would parse as local time.
    assert snapshot["created_at"].endswith("+00:00")


def test_repo_status_read_query_count_is_constant_in_repo_count(workspace_factory):
    """The snapshot join is 2 queries TOTAL (max-per-repo + rows), never per-repo:
    the read is polled every 30s by three surfaces, so an N+1 here compounds."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    ws = workspace_factory()
    repos = [f"wanjala-dev/repo-{i}" for i in range(1, 4)]
    VcsConnection.objects.create(
        workspace=ws,
        provider=VcsConnection.Provider.GITHUB,
        name="GitHub",
        repo_allowlist=[_REPO],
        status=VcsConnection.Status.CONNECTED,
    )
    _snapshot(ws, _REPO, total=1, low=1)

    with CaptureQueriesContext(connection) as one_repo:
        ListRepoScanStatusUseCase().execute(workspace_id=ws.id, cooldown_seconds=_COOLDOWN)

    VcsConnection.objects.create(
        workspace=ws,
        provider=VcsConnection.Provider.GITHUB,
        name="GitHub 2",
        repo_allowlist=repos,
        status=VcsConnection.Status.CONNECTED,
    )
    for repo in repos:
        _snapshot(ws, repo, total=2, high=1, low=1, age=timedelta(hours=1))
        _snapshot(ws, repo, total=3, medium=3)

    with CaptureQueriesContext(connection) as four_repos:
        rows = ListRepoScanStatusUseCase().execute(workspace_id=ws.id, cooldown_seconds=_COOLDOWN)

    assert len(rows) == 4
    assert all(r["last_snapshot"] is not None for r in rows)
    assert {r["last_snapshot"]["total_findings"] for r in rows if r["repo"] != _REPO} == {3}
    assert len(four_repos) == len(one_repo)


class TestMergeRescanCooldownExemption:
    """#118: the post-merge verification rescan is the ONE trigger path exempt
    from the completed-run cooldown — manual stays locked, and the exempt
    dispatch stamps ``merge_rescan`` provenance."""

    def test_cooldown_blocks_manual_but_not_the_merge_rescan(self, workspace_factory, _dispatch_spy):
        ws = workspace_factory()
        _connection(ws)
        _run(ws, status=ScanRun.Status.COMPLETED, completed_delta=timedelta(minutes=10))
        use_case = TriggerRepoScanUseCase()

        # The manual path keeps the anti-spam window (the narrowness guarantee)...
        with pytest.raises(RepoScanRejected) as excinfo:
            use_case.execute(workspace_id=ws.id, repo=_REPO)
        assert excinfo.value.code == "scan_cooldown"
        assert _dispatch_spy == []

        # ...the merge-rescan path dispatches NOW, with its own provenance.
        result = use_case.execute(workspace_id=ws.id, repo=_REPO, trigger="merge_rescan", bypass_cooldown=True)

        assert result["task_id"] == "task-1"
        assert len(_dispatch_spy) == 1
        assert _dispatch_spy[0]["trigger"] == "merge_rescan"

    def test_merge_rescan_still_respects_a_running_scan(self, workspace_factory, _dispatch_spy):
        """The exemption is cooldown-only: one-in-flight always holds."""
        ws = workspace_factory()
        _connection(ws)
        _run(ws, status=ScanRun.Status.RUNNING)

        with pytest.raises(RepoScanRejected) as excinfo:
            TriggerRepoScanUseCase().execute(
                workspace_id=ws.id, repo=_REPO, trigger="merge_rescan", bypass_cooldown=True
            )

        assert excinfo.value.code == "scan_already_running"
        assert _dispatch_spy == []

    def test_merge_rescan_never_bypasses_consent(self, workspace_factory, _dispatch_spy):
        """Cooldown exemption must not widen consent: an un-allowlisted repo is
        rejected before the budget gate is ever consulted."""
        ws = workspace_factory()  # no connection at all → nothing is allowlisted

        with pytest.raises(RepoScanRejected) as excinfo:
            TriggerRepoScanUseCase().execute(
                workspace_id=ws.id, repo=_REPO, trigger="merge_rescan", bypass_cooldown=True
            )

        assert excinfo.value.code == "repo_not_allowlisted"
        assert _dispatch_spy == []
